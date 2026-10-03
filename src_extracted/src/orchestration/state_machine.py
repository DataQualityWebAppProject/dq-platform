"""Pipeline state machine for the NLQ Quality Benchmark.

Implements the explicit state machine defined in ADR-001.
Every transition is recorded as an immutable TransitionRecord.
No framework dependency (no LangGraph, AutoGen, Prefect).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import FrozenSet

from models.agent_result import AgentResult


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------

class PipelineState:
    INGESTED       = "INGESTED"
    CANONICALIZED  = "CANONICALIZED"
    SCOPED         = "SCOPED"
    PLANNED        = "PLANNED"
    ROUTED         = "ROUTED"
    GENERATED      = "GENERATED"
    AST_VALID      = "AST_VALID"
    EXECUTED       = "EXECUTED"
    TESTED         = "TESTED"
    META_VALIDATED = "META_VALIDATED"
    REPAIRED       = "REPAIRED"
    # Terminal states
    VALIDATED      = "VALIDATED"
    HUMAN_REVIEW   = "HUMAN_REVIEW"
    ABSTAIN        = "ABSTAIN"
    FAILED         = "FAILED"


TERMINAL_STATES: FrozenSet[str] = frozenset({
    PipelineState.VALIDATED,
    PipelineState.HUMAN_REVIEW,
    PipelineState.ABSTAIN,
    PipelineState.FAILED,
})

# Legal transitions: from_state -> set of allowed to_states
ALLOWED_TRANSITIONS: dict[str, FrozenSet[str]] = {
    PipelineState.INGESTED:       frozenset({PipelineState.CANONICALIZED, PipelineState.HUMAN_REVIEW, PipelineState.ABSTAIN, PipelineState.FAILED}),
    PipelineState.CANONICALIZED:  frozenset({PipelineState.SCOPED,        PipelineState.HUMAN_REVIEW, PipelineState.ABSTAIN, PipelineState.FAILED}),
    PipelineState.SCOPED:         frozenset({PipelineState.PLANNED,       PipelineState.HUMAN_REVIEW, PipelineState.ABSTAIN, PipelineState.FAILED}),
    PipelineState.PLANNED:        frozenset({PipelineState.ROUTED,        PipelineState.HUMAN_REVIEW, PipelineState.ABSTAIN, PipelineState.FAILED}),
    PipelineState.ROUTED:         frozenset({PipelineState.GENERATED,     PipelineState.HUMAN_REVIEW, PipelineState.ABSTAIN, PipelineState.FAILED}),
    PipelineState.GENERATED:      frozenset({PipelineState.AST_VALID,     PipelineState.REPAIRED,     PipelineState.HUMAN_REVIEW, PipelineState.ABSTAIN, PipelineState.FAILED}),
    PipelineState.AST_VALID:      frozenset({PipelineState.EXECUTED,      PipelineState.REPAIRED,     PipelineState.HUMAN_REVIEW, PipelineState.ABSTAIN, PipelineState.FAILED}),
    PipelineState.EXECUTED:       frozenset({PipelineState.TESTED,        PipelineState.REPAIRED,     PipelineState.HUMAN_REVIEW, PipelineState.ABSTAIN, PipelineState.FAILED}),
    PipelineState.TESTED:         frozenset({PipelineState.META_VALIDATED,PipelineState.REPAIRED,     PipelineState.HUMAN_REVIEW, PipelineState.ABSTAIN, PipelineState.FAILED}),
    PipelineState.META_VALIDATED: frozenset({PipelineState.VALIDATED,     PipelineState.REPAIRED,     PipelineState.HUMAN_REVIEW, PipelineState.ABSTAIN, PipelineState.FAILED}),
    PipelineState.REPAIRED:       frozenset({PipelineState.GENERATED,     PipelineState.VALIDATED,    PipelineState.HUMAN_REVIEW, PipelineState.ABSTAIN, PipelineState.FAILED}),
    # Terminal states have no outgoing transitions
    PipelineState.VALIDATED:      frozenset(),
    PipelineState.HUMAN_REVIEW:   frozenset(),
    PipelineState.ABSTAIN:        frozenset(),
    PipelineState.FAILED:         frozenset(),
}


# ---------------------------------------------------------------------------
# Transition record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TransitionRecord:
    """Immutable record of a single state-machine transition."""
    from_state:   str
    to_state:     str
    agent_id:     str
    input_hash:   str
    output_hash:  str
    prompt_hash:  str | None
    elapsed_ms:   float
    errors:       tuple[str, ...]
    trace_id:     str
    timestamp_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Invalid transition error
# ---------------------------------------------------------------------------

class InvalidTransitionError(ValueError):
    """Raised when a transition that violates the state machine is attempted."""


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class PipelineStateMachine:
    """Explicit state machine for a single pipeline execution.

    Parameters
    ----------
    trace_id:
        Unique identifier for this pipeline run; used in all transition records.
    max_repairs:
        Maximum number of REPAIRED transitions allowed before the machine
        forces HUMAN_REVIEW or FAILED.
    """

    def __init__(self, trace_id: str, max_repairs: int = 3) -> None:
        self._trace_id = trace_id
        self._max_repairs = max_repairs
        self._current_state: str = PipelineState.INGESTED
        self._repair_count: int = 0
        self._history: list[TransitionRecord] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> str:
        """Current state of the pipeline."""
        return self._current_state

    @property
    def history(self) -> list[TransitionRecord]:
        """Read-only view of all recorded transitions."""
        return list(self._history)

    @property
    def repair_count(self) -> int:
        """Number of REPAIRED transitions so far."""
        return self._repair_count

    @property
    def is_terminal(self) -> bool:
        """True if the machine is in a terminal state."""
        return self._current_state in TERMINAL_STATES

    def transition(self, result: AgentResult) -> None:
        """Advance the state machine using an AgentResult.

        The target state is taken from ``result.to_state``.  If the transition
        is illegal, an ``InvalidTransitionError`` is raised and the state is
        NOT changed.

        Repair budget enforcement: if the machine attempts to enter REPAIRED
        more than ``max_repairs`` times, the transition target is redirected
        to HUMAN_REVIEW automatically.

        Parameters
        ----------
        result:
            The result returned by the agent that ran in the current state.

        Raises
        ------
        InvalidTransitionError
            If the transition from ``current_state`` to ``result.to_state``
            is not listed in ``ALLOWED_TRANSITIONS``.
        RuntimeError
            If called when the machine is already in a terminal state.
        """
        if self.is_terminal:
            raise RuntimeError(
                f"Cannot transition from terminal state '{self._current_state}'. "
                "Create a new PipelineStateMachine for a new run."
            )

        target = result.to_state

        # Repair budget enforcement
        if target == PipelineState.REPAIRED:
            if self._repair_count >= self._max_repairs:
                target = PipelineState.HUMAN_REVIEW

        allowed = ALLOWED_TRANSITIONS.get(self._current_state, frozenset())
        if target not in allowed:
            raise InvalidTransitionError(
                f"Transition '{self._current_state}' → '{target}' is not allowed. "
                f"Allowed: {sorted(allowed)}"
            )

        record = TransitionRecord(
            from_state=self._current_state,
            to_state=target,
            agent_id=result.agent_id,
            input_hash=result.input_hash,
            output_hash=result.output_hash,
            prompt_hash=result.prompt_hash,
            elapsed_ms=result.elapsed_ms,
            errors=tuple(str(d) for d in result.diagnostics if d.get("level") == "error"),
            trace_id=self._trace_id,
        )
        self._history.append(record)

        if target == PipelineState.REPAIRED:
            self._repair_count += 1

        self._current_state = target
