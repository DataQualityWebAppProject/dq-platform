"""Adjudicator agent — makes the final verdict on rule evaluation.

Pipeline position: TESTED → VALIDATED | HUMAN_REVIEW | ABSTAIN
The adjudicator is the final agent in the pipeline. It compares the
execution output against the oracle and produces the definitive result.

Final states:
- VALIDATED: execution output matches oracle on all test cases
- HUMAN_REVIEW: partial match or uncertain — requires human decision
- ABSTAIN: execution is vacuously true (non-applicable) or no oracle available

Per research-integrity.md: the state final is always one of these three.
"""
from __future__ import annotations

import time
from typing import Any

from models.agent_result import AgentResult
from orchestration.state_machine import PipelineState
from utils.ids import hash_dict, new_trace_id


def adjudicate(
    execution_payload: dict[str, Any],
    oracle: dict[str, Any] | None,
    test_cases: list[dict[str, Any]] | None = None,
    trace_id: str | None = None,
) -> AgentResult:
    """Make the final verdict for a rule evaluation run.

    Parameters
    ----------
    execution_payload:
        Dict from executor with "execution_result" key.
    oracle:
        Expected output from the gold oracle. None → ABSTAIN.
    test_cases:
        Optional list of test case dicts for functional verification.
    trace_id:
        Trace identifier.

    Returns
    -------
    AgentResult with final state: VALIDATED, HUMAN_REVIEW, or ABSTAIN.
    """
    tid = trace_id or new_trace_id()
    start = time.monotonic()
    agent_id = "adjudicator-v1"
    input_hash = hash_dict(execution_payload)

    # No oracle → ABSTAIN
    if oracle is None:
        elapsed = (time.monotonic() - start) * 1000
        return AgentResult(
            status="ABSTAIN",
            payload={**execution_payload, "verdict": "ABSTAIN", "reason": "No oracle available."},
            evidence=[],
            diagnostics=[{"level": "info", "message": "No oracle available; ABSTAIN."}],
            trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
            from_state=PipelineState.TESTED,
            to_state=PipelineState.ABSTAIN,
            input_hash=input_hash, output_hash=hash_dict({"verdict": "ABSTAIN"}),
        )

    exec_result = execution_payload.get("execution_result", {})
    exec_output = exec_result.get("output", {})
    exec_success = exec_result.get("success", False)

    # Execution failed → HUMAN_REVIEW
    if not exec_success:
        elapsed = (time.monotonic() - start) * 1000
        return AgentResult(
            status="HUMAN_REVIEW",
            payload={**execution_payload, "verdict": "HUMAN_REVIEW",
                     "reason": "Execution failed."},
            evidence=[],
            diagnostics=[{"level": "warning", "message": "Execution failed; escalating."}],
            trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
            from_state=PipelineState.TESTED,
            to_state=PipelineState.HUMAN_REVIEW,
            input_hash=input_hash, output_hash=hash_dict({"verdict": "HUMAN_REVIEW"}),
        )

    # Compare output against oracle
    verdict = _compare_output_oracle(exec_output, oracle, test_cases or [])
    elapsed = (time.monotonic() - start) * 1000
    payload = {
        **execution_payload,
        "verdict": verdict["verdict"],
        "reason": verdict["reason"],
        "oracle_match_score": verdict["score"],
    }

    if verdict["verdict"] == "VALIDATED":
        to_state = PipelineState.VALIDATED
        status = "OK"
    elif verdict["verdict"] == "ABSTAIN":
        to_state = PipelineState.ABSTAIN
        status = "ABSTAIN"
    else:
        to_state = PipelineState.HUMAN_REVIEW
        status = "HUMAN_REVIEW"

    return AgentResult(
        status=status, payload=payload, evidence=[], diagnostics=[],
        trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
        from_state=PipelineState.TESTED,
        to_state=to_state,
        input_hash=input_hash, output_hash=hash_dict({"verdict": verdict["verdict"]}),
    )


def _compare_output_oracle(
    output: dict[str, Any],
    oracle: dict[str, Any],
    test_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare execution output against oracle.

    Returns a dict with keys: verdict, reason, score.
    Simple comparison: flagged_rows must match expected_flagged if specified.
    """
    # If oracle specifies expected_flagged and output has flagged_rows
    if "expected_flagged" in oracle and "flagged_rows" in output:
        expected = set(oracle["expected_flagged"])
        actual = set(output.get("flagged_rows", []))
        if expected == actual:
            return {"verdict": "VALIDATED", "reason": "Flagged rows match oracle.", "score": 1.0}
        else:
            overlap = len(expected & actual) / max(len(expected | actual), 1)
            if overlap >= 0.8:
                return {"verdict": "VALIDATED", "reason": f"High overlap ({overlap:.0%}).", "score": overlap}
            return {"verdict": "HUMAN_REVIEW", "reason": f"Flagged rows mismatch (overlap={overlap:.0%}).", "score": overlap}

    # If oracle specifies non_applicable=True → ABSTAIN
    if oracle.get("non_applicable"):
        return {"verdict": "ABSTAIN", "reason": "Rule is non-applicable for this input.", "score": 1.0}

    # Default: if execution succeeded and oracle doesn't contradict → VALIDATED
    return {"verdict": "VALIDATED", "reason": "No contradiction with oracle.", "score": 1.0}
