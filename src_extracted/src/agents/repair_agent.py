"""Repair agent — attempts to fix failed code with structured feedback.

Pipeline position: REPAIRED → GENERATED (retry) or HUMAN_REVIEW (max attempts)
The repair agent receives structured diagnostics from the AST guard or executor
and produces a modified version of the code.

Design rules:
- Maximum attempts is configurable (default: 3, from ADR-001).
- Each attempt increments a counter stored in the payload.
- When max attempts is reached, transitions to HUMAN_REVIEW.
- Repair history is preserved (append-only).
"""
from __future__ import annotations

import time
from typing import Any, Callable

from models.agent_result import AgentResult
from orchestration.state_machine import PipelineState
from utils.ids import hash_dict, hash_content, new_trace_id


DEFAULT_MAX_REPAIRS = 3


def repair_code(
    code_payload: dict[str, Any],
    diagnostics: list[dict[str, Any]],
    attempt: int = 1,
    max_attempts: int = DEFAULT_MAX_REPAIRS,
    trace_id: str | None = None,
    llm_fn: Callable[[str, list[dict[str, Any]]], str] | None = None,
) -> AgentResult:
    """Attempt to repair code based on structured diagnostics.

    Parameters
    ----------
    code_payload:
        Dict with key "code" and optionally "repair_history".
    diagnostics:
        Structured error messages from the previous failure.
    attempt:
        Current attempt number (1-based).
    max_attempts:
        Maximum number of repair attempts allowed.
    trace_id:
        Trace identifier.
    llm_fn:
        Optional LLM function: (code, diagnostics) → repaired code.
        If None, returns HUMAN_REVIEW immediately.

    Returns
    -------
    AgentResult:
    - status="OK" if a repair was produced → to_state=GENERATED
    - status="HUMAN_REVIEW" if max attempts reached or no llm_fn
    """
    tid = trace_id or new_trace_id()
    start = time.monotonic()
    agent_id = "repair-agent-v1"
    code = code_payload.get("code", "")
    input_hash = hash_content(code)

    # Append to repair history (append-only)
    repair_history: list[dict[str, Any]] = list(
        code_payload.get("repair_history", [])
    )
    repair_history.append({
        "attempt": attempt,
        "diagnostics": diagnostics,
        "code_before_repair": code[:500],  # truncated for space
    })

    if attempt > max_attempts:
        elapsed = (time.monotonic() - start) * 1000
        payload = code_payload.copy()
        payload["repair_history"] = repair_history
        return AgentResult(
            status="HUMAN_REVIEW",
            payload=payload,
            evidence=[],
            diagnostics=[{
                "level": "warning",
                "message": f"Max repair attempts ({max_attempts}) exceeded. Human review required.",
            }],
            trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
            from_state=PipelineState.REPAIRED,
            to_state=PipelineState.HUMAN_REVIEW,
            input_hash=input_hash, output_hash=hash_dict({"attempt": attempt}),
        )

    if llm_fn is None:
        # No LLM available — cannot repair automatically
        elapsed = (time.monotonic() - start) * 1000
        payload = code_payload.copy()
        payload["repair_history"] = repair_history
        return AgentResult(
            status="HUMAN_REVIEW",
            payload=payload,
            evidence=[],
            diagnostics=[{
                "level": "warning",
                "message": "No LLM repair function provided. Human review required.",
            }],
            trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
            from_state=PipelineState.REPAIRED,
            to_state=PipelineState.HUMAN_REVIEW,
            input_hash=input_hash, output_hash=hash_dict({}),
        )

    try:
        repaired_code = llm_fn(code, diagnostics)
        elapsed = (time.monotonic() - start) * 1000
        repaired_hash = hash_content(repaired_code)
        repair_history[-1]["code_after_repair"] = repaired_code[:500]

        payload = code_payload.copy()
        payload["code"] = repaired_code
        payload["code_hash"] = repaired_hash
        payload["repair_history"] = repair_history
        payload["repair_attempt"] = attempt

        return AgentResult(
            status="OK",
            payload=payload,
            evidence=[],
            diagnostics=[],
            trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
            from_state=PipelineState.REPAIRED,
            to_state=PipelineState.GENERATED,
            input_hash=input_hash, output_hash=repaired_hash,
        )

    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        payload = code_payload.copy()
        payload["repair_history"] = repair_history
        return AgentResult(
            status="ERROR", payload=payload, evidence=[],
            diagnostics=[{"level": "error", "message": str(exc)}],
            trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
            from_state=PipelineState.REPAIRED,
            to_state=PipelineState.FAILED,
            input_hash=input_hash, output_hash=hash_dict({}),
        )
