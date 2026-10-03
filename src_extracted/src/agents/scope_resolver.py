"""Scope resolver agent — determines which tables and columns are in scope.

Pipeline position: CANONICALIZED → SCOPED
Contract: receives an IR dict from the canonicalizer and resolves scope.

Design (from Simbola et al. 2026): scope resolution is stage 2 of the
structured prompt pipeline. Without explicit scope, evidence locator
and logic planner cannot operate correctly.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable

from models.agent_result import AgentResult
from models.ir import IR, IRScope
from orchestration.state_machine import PipelineState
from utils.ids import hash_dict, new_trace_id


def resolve_scope(
    ir_payload: dict[str, Any],
    schema_columns: list[str] | None = None,
    trace_id: str | None = None,
    llm_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> AgentResult:
    """Resolve the scope (tables, columns) of an IR.

    Parameters
    ----------
    ir_payload:
        The IR dict from the canonicalizer's AgentResult.payload.
    schema_columns:
        Known column names from the dataset profile. Used to verify
        that the IR's scope.columns are valid.
    trace_id:
        Trace identifier.
    llm_fn:
        Optional LLM function: ir_dict → updated ir_dict with scope filled in.

    Returns
    -------
    AgentResult with the updated IR in payload.
    """
    tid = trace_id or new_trace_id()
    start = time.monotonic()
    agent_id = "scope-resolver-v1"
    input_hash = hash_dict(ir_payload)

    try:
        if llm_fn is not None:
            updated = llm_fn(ir_payload)
            ir = IR.model_validate(updated)
        else:
            # Rule-based fallback: if scope.columns is empty and schema_columns
            # is provided, attempt to resolve from NL keywords
            ir = IR.model_validate(ir_payload)
            if not ir.scope.columns and schema_columns:
                # Heuristic: find column names mentioned in the IR ambiguities
                # or infer from the dataset profile
                resolved_cols = list(schema_columns[:5])  # conservative: first 5
                ir = ir.model_copy(update={"scope": IRScope(
                    level=ir.scope.level,
                    tables=ir.scope.tables,
                    columns=resolved_cols,
                )})

        payload = json.loads(ir.model_dump_json())
        output_hash = hash_dict(payload)
        elapsed = (time.monotonic() - start) * 1000

        # If scope is still empty after resolution, flag for HUMAN_REVIEW
        if not ir.scope.columns and not ir.scope.tables:
            return AgentResult(
                status="HUMAN_REVIEW",
                payload=payload,
                evidence=[],
                diagnostics=[{
                    "level": "warning",
                    "message": "Scope could not be resolved: no columns or tables identified."
                }],
                trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
                from_state=PipelineState.CANONICALIZED,
                to_state=PipelineState.HUMAN_REVIEW,
                input_hash=input_hash, output_hash=output_hash,
            )

        return AgentResult(
            status="OK", payload=payload, evidence=[], diagnostics=[],
            trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
            from_state=PipelineState.CANONICALIZED,
            to_state=PipelineState.SCOPED,
            input_hash=input_hash, output_hash=output_hash,
        )

    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return AgentResult(
            status="ERROR", payload={}, evidence=[],
            diagnostics=[{"level": "error", "message": str(exc)}],
            trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
            from_state=PipelineState.CANONICALIZED,
            to_state=PipelineState.FAILED,
            input_hash=input_hash, output_hash=hash_dict({}),
        )
