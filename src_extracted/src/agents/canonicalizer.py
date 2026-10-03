"""Canonicalizer agent — transforms NL rule text into a structured IR skeleton.

Pipeline position: INGESTED → CANONICALIZED
Contract: returns AgentResult with payload containing the IR dict.

This agent does NOT call an LLM by default — it produces a skeleton IR
from the rule's existing metadata (dimension, complexity from RuleRecord).
The LLM-backed canonicalization is injected via the `llm_fn` parameter.

Design (from Simbola et al. 2026): canonicalization is the first gate.
Without it, scope resolution and logic planning are undefined.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Callable

from models.agent_result import AgentResult
from models.ir import IR, IRScope, IRLogic, IRAction
from models.rule import RuleRecord
from orchestration.state_machine import PipelineState
from utils.ids import hash_dict, new_trace_id


def _default_skeleton_ir(rule: RuleRecord) -> IR:
    """Build a minimal IR skeleton from the RuleRecord's metadata fields."""
    return IR(
        rule_id=rule.rule_id,
        dimension=rule.dimension,
        complexity=rule.complexity,
        scope=IRScope(level="row"),
        logic=IRLogic(operator="NONE"),
        action=IRAction(mode="detect"),
    )


def canonicalize(
    rule: RuleRecord,
    trace_id: str | None = None,
    llm_fn: Callable[[str], dict[str, Any]] | None = None,
) -> AgentResult:
    """Run the canonicalization step for a single rule.

    Parameters
    ----------
    rule:
        The RuleRecord to canonicalize.
    trace_id:
        Trace identifier (generated if not provided).
    llm_fn:
        Optional LLM function: nl_text → IR dict.
        If None, uses the skeleton builder (metadata only, no inference).

    Returns
    -------
    AgentResult with:
    - status="OK" if canonicalization produced a valid IR
    - status="HUMAN_REVIEW" if the IR is ambiguous or underspecified
    - status="ABSTAIN" if the rule is too complex to canonicalize
    - status="ERROR" on unexpected failure
    """
    tid = trace_id or new_trace_id()
    start = time.monotonic()
    agent_id = "canonicalizer-v1"

    input_hash = hash_dict({"rule_id": rule.rule_id, "nl_text": rule.nl_text})

    try:
        if llm_fn is not None:
            raw_ir_dict = llm_fn(rule.nl_text)
            # Validate the returned dict against the IR model
            raw_ir_dict["rule_id"] = rule.rule_id  # enforce correct rule_id
            ir = IR.model_validate(raw_ir_dict)
        else:
            ir = _default_skeleton_ir(rule)

        payload = json.loads(ir.model_dump_json())
        output_hash = hash_dict(payload)
        elapsed = (time.monotonic() - start) * 1000

        # If rule is marked ABSTAIN complexity, return ABSTAIN
        if rule.complexity == "ABSTAIN":
            return AgentResult(
                status="ABSTAIN",
                payload=payload,
                evidence=[],
                diagnostics=[{"level": "info", "message": "Rule complexity=ABSTAIN; skipping."}],
                trace_id=tid,
                elapsed_ms=elapsed,
                agent_id=agent_id,
                from_state=PipelineState.INGESTED,
                to_state=PipelineState.ABSTAIN,
                input_hash=input_hash,
                output_hash=output_hash,
            )

        return AgentResult(
            status="OK",
            payload=payload,
            evidence=[],
            diagnostics=[],
            trace_id=tid,
            elapsed_ms=elapsed,
            agent_id=agent_id,
            from_state=PipelineState.INGESTED,
            to_state=PipelineState.CANONICALIZED,
            input_hash=input_hash,
            output_hash=output_hash,
        )

    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return AgentResult(
            status="ERROR",
            payload={},
            evidence=[],
            diagnostics=[{"level": "error", "message": str(exc)}],
            trace_id=tid,
            elapsed_ms=elapsed,
            agent_id=agent_id,
            from_state=PipelineState.INGESTED,
            to_state=PipelineState.FAILED,
            input_hash=input_hash,
            output_hash=hash_dict({}),
        )


def evaluate_ir(ir: IR, gold_ir: IR | None) -> dict[str, Any]:
    """Compare a predicted IR against the gold IR.

    Returns a dict with match booleans for each field.
    Returns all None if gold_ir is None (no gold available).
    """
    if gold_ir is None:
        return {
            "dimension_match": None,
            "complexity_match": None,
            "scope_level_match": None,
            "operator_match": None,
            "action_mode_match": None,
        }
    return {
        "dimension_match": ir.dimension == gold_ir.dimension,
        "complexity_match": ir.complexity == gold_ir.complexity,
        "scope_level_match": ir.scope.level == gold_ir.scope.level,
        "operator_match": ir.logic.operator == gold_ir.logic.operator,
        "action_mode_match": ir.action.mode == gold_ir.action.mode,
    }
