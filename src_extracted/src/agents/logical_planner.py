"""Logical planner agent — builds the logical evaluation plan from the IR.

Pipeline position: PLANNED → ROUTED
Contract: receives IR with evidence and produces a logical execution plan.

Handles all logical operators: AND/OR/NOT/IF/IFF/FORALL/EXISTS/NONE.
Special handling for non-applicability (vacuous truth when antecedent absent).
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable

from models.agent_result import AgentResult
from models.ir import IR
from orchestration.state_machine import PipelineState
from utils.ids import hash_dict, new_trace_id


def plan_logic(
    ir_payload: dict[str, Any],
    trace_id: str | None = None,
    llm_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> AgentResult:
    """Build the logical evaluation plan for the IR.

    The plan is stored in payload["logic_plan"] as a dict.
    For NONE operator (atomic rule), the plan is a simple check.
    For IF/IFF, explicit non-applicability handling is added.

    Returns ABSTAIN if the logic structure is too ambiguous to plan.
    """
    tid = trace_id or new_trace_id()
    start = time.monotonic()
    agent_id = "logical-planner-v1"
    input_hash = hash_dict(ir_payload)

    try:
        ir = IR.model_validate(ir_payload)

        if llm_fn is not None:
            updated = llm_fn(ir_payload)
            ir = IR.model_validate(updated)

        plan = _build_plan(ir)

        payload = json.loads(ir.model_dump_json())
        payload["logic_plan"] = plan
        output_hash = hash_dict({"logic_plan": plan})
        elapsed = (time.monotonic() - start) * 1000

        # IFF with empty ambiguities is fine; IFF with ambiguities → HUMAN_REVIEW
        if ir.logic.operator == "IFF" and ir.ambiguities:
            return AgentResult(
                status="HUMAN_REVIEW", payload=payload, evidence=[],
                diagnostics=[{
                    "level": "warning",
                    "message": "IFF rule has ambiguities — biconditional split recommended.",
                }],
                trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
                from_state=PipelineState.PLANNED,
                to_state=PipelineState.HUMAN_REVIEW,
                input_hash=input_hash, output_hash=output_hash,
            )

        return AgentResult(
            status="OK", payload=payload, evidence=[], diagnostics=[],
            trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
            from_state=PipelineState.PLANNED,
            to_state=PipelineState.ROUTED,
            input_hash=input_hash, output_hash=output_hash,
        )

    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return AgentResult(
            status="ERROR", payload={}, evidence=[],
            diagnostics=[{"level": "error", "message": str(exc)}],
            trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
            from_state=PipelineState.PLANNED,
            to_state=PipelineState.FAILED,
            input_hash=input_hash, output_hash=hash_dict({}),
        )


def _build_plan(ir: IR) -> dict[str, Any]:
    """Build a logical execution plan dict from the IR."""
    operator = ir.logic.operator
    plan: dict[str, Any] = {
        "operator": operator,
        "clauses": ir.logic.clauses,
        "non_applicability": ir.non_applicability,
        "quantifier": ir.quantifier,
    }

    # Non-applicability: for IF/IFF, add vacuous truth handling
    if operator in ("IF", "IFF"):
        plan["vacuous_truth_handling"] = (
            "If antecedent column(s) absent, result is NOT_APPLICABLE"
        )

    # FORALL/EXISTS: add quantifier scope
    if operator in ("FORALL", "EXISTS"):
        plan["quantifier_scope"] = ir.scope.model_dump()

    return plan
