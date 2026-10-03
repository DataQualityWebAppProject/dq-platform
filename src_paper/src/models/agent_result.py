"""AgentResult — standard contract for all agent outputs.

Every agent in the pipeline (canonicalizer, scope resolver, planner, generator,
AST guard, sandbox, repair agent, adjudicator …) returns an ``AgentResult``.
This ensures that the orchestrator can handle errors, route to human review and
build full traces without knowing the internal logic of each agent.

The ``status`` field drives the state machine:

* ``OK``          — agent succeeded; ``payload`` holds the result.
* ``HUMAN_REVIEW`` — agent is uncertain; requires human decision.
* ``ABSTAIN``     — agent declines to act (e.g. ambiguous rule, missing evidence).
* ``ERROR``       — unexpected failure; ``diagnostics`` must explain the cause.

Extended fields (``agent_id``, ``from_state``, ``to_state``, ``input_hash``,
``output_hash``, ``prompt_hash``) enable full audit trails and reproducibility
checks without storing raw payloads in the main database.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


_StatusT = Literal["OK", "HUMAN_REVIEW", "ABSTAIN", "ERROR"]


class AgentResult(BaseModel):
    """Standardised result envelope returned by every agent.

    Core fields (from design.md)
    ----------------------------
    status
        High-level outcome of the agent execution.
    payload
        Agent-specific output artefact (IR, code, verdict, …).
    evidence
        List of evidence items that informed the decision.
    diagnostics
        Structured diagnostic messages (warnings, errors, reasoning steps).
    trace_id
        Unique identifier linking this result to an end-to-end trace.
    elapsed_ms
        Wall-clock time consumed by the agent in milliseconds.

    Audit fields
    ------------
    agent_id
        Stable identifier of the agent that produced this result
        (e.g. ``"canonicalizer-v1"``).
    from_state
        State-machine state *before* this agent ran.
    to_state
        State-machine state *after* this agent ran.
    input_hash
        SHA-256 (hex) of the serialised input passed to the agent.
    output_hash
        SHA-256 (hex) of the serialised ``payload``.
    prompt_hash
        SHA-256 (hex) of the prompt template + filled variables, if applicable.
    """

    # Core contract — must match design.md exactly
    status: _StatusT
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    trace_id: str
    elapsed_ms: float = Field(ge=0.0)

    # Audit / traceability extensions
    agent_id: str
    from_state: str
    to_state: str
    input_hash: str
    output_hash: str
    prompt_hash: str | None = None

    model_config = {"extra": "forbid"}
