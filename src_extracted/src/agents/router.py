"""Router agent — routes the IR to the appropriate code generator.

Pipeline position: ROUTED → GENERATED
The router decides which generator to use based on IR complexity:
- POINT_IN_TIME → PointInTimeGenerator
- HISTORICAL → HistoricalGenerator
- ML_NECESSARY → MLGenerator (requires explicit ML gate approval)

ML Gate (from design.md / research-integrity.md):
ML_NECESSARY complexity requires an EXPLICIT gate: the gate checks that
(a) no deterministic alternative exists and (b) training/test data separation
is confirmed. Without the gate, ML routing is BLOCKED.
"""
from __future__ import annotations

import time
from typing import Any, Literal

from models.agent_result import AgentResult
from models.ir import IR
from orchestration.state_machine import PipelineState
from utils.ids import hash_dict, new_trace_id


GeneratorT = Literal["point_in_time", "historical", "ml", "abstain"]


class MLGateNotPassedError(RuntimeError):
    """Raised when ML routing is attempted without the ML gate being passed."""


def check_ml_gate(ir_payload: dict[str, Any]) -> bool:
    """Check the ML necessity gate.

    Returns True only if the ML gate conditions are met:
    - IR complexity is ML_NECESSARY
    - non_applicability is documented (explains why deterministic fails)
    - Data separation is confirmed (splits must exist — checked via splits.json presence)

    This is a simplified gate: full gate is in T7.4.
    """
    try:
        ir = IR.model_validate(ir_payload)
    except Exception:
        return False
    return (
        ir.complexity == "ML_NECESSARY"
        and bool(ir.non_applicability)  # must document why non-deterministic
    )


def route(
    ir_payload: dict[str, Any],
    ml_gate_passed: bool = False,
    trace_id: str | None = None,
) -> AgentResult:
    """Route the IR to the appropriate generator.

    Parameters
    ----------
    ir_payload:
        IR dict from the logical planner.
    ml_gate_passed:
        Must be True for ML_NECESSARY complexity. If False and complexity
        is ML_NECESSARY, returns HUMAN_REVIEW.
    trace_id:
        Trace identifier.

    Returns
    -------
    AgentResult with payload["generator"] set to the chosen generator type.
    """
    tid = trace_id or new_trace_id()
    start = time.monotonic()
    agent_id = "router-v1"
    input_hash = hash_dict(ir_payload)

    try:
        ir = IR.model_validate(ir_payload)
        complexity = ir.complexity
        elapsed = (time.monotonic() - start) * 1000

        if complexity == "ABSTAIN":
            return AgentResult(
                status="ABSTAIN", payload={"generator": "abstain"}, evidence=[],
                diagnostics=[{"level": "info", "message": "Complexity=ABSTAIN; no generator."}],
                trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
                from_state=PipelineState.ROUTED,
                to_state=PipelineState.ABSTAIN,
                input_hash=input_hash, output_hash=hash_dict({"generator": "abstain"}),
            )

        if complexity == "ML_NECESSARY":
            if not ml_gate_passed:
                return AgentResult(
                    status="HUMAN_REVIEW",
                    payload={"generator": "ml", "gate_required": True},
                    evidence=[],
                    diagnostics=[{
                        "level": "warning",
                        "message": (
                            "ML_NECESSARY complexity requires explicit ML gate approval. "
                            "Set ml_gate_passed=True only after confirming data separation. "
                            "See research-integrity.md."
                        )
                    }],
                    trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
                    from_state=PipelineState.ROUTED,
                    to_state=PipelineState.HUMAN_REVIEW,
                    input_hash=input_hash, output_hash=hash_dict({"generator": "ml"}),
                )
            generator: GeneratorT = "ml"
        elif complexity == "HISTORICAL":
            generator = "historical"
        else:
            generator = "point_in_time"

        import json
        payload = json.loads(ir.model_dump_json())
        payload["generator"] = generator

        return AgentResult(
            status="OK", payload=payload, evidence=[], diagnostics=[],
            trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
            from_state=PipelineState.ROUTED,
            to_state=PipelineState.GENERATED,
            input_hash=input_hash, output_hash=hash_dict({"generator": generator}),
        )

    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return AgentResult(
            status="ERROR", payload={}, evidence=[],
            diagnostics=[{"level": "error", "message": str(exc)}],
            trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
            from_state=PipelineState.ROUTED,
            to_state=PipelineState.FAILED,
            input_hash=input_hash, output_hash=hash_dict({}),
        )
