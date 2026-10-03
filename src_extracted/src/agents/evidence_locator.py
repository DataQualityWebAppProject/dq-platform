"""Evidence locator agent — finds and validates evidence for rule evaluation.

Pipeline position: SCOPED → PLANNED (or ABSTAIN if evidence missing)
Contract: receives a scoped IR and identifies what evidence is needed.

Design (from Simbola et al. 2026): evidence localization is stage 3.
If evidence cannot be located, the correct action is ABSTAIN, not guessing.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable

from models.agent_result import AgentResult
from models.ir import IR
from orchestration.state_machine import PipelineState
from utils.ids import hash_dict, new_trace_id


_EVIDENCE_REQUIRING_EXTERNAL_REF = frozenset({"accuracy", "timeliness"})


def locate_evidence(
    ir_payload: dict[str, Any],
    dataset_columns: list[str] | None = None,
    trace_id: str | None = None,
    llm_fn: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None,
) -> AgentResult:
    """Locate evidence items for the given scoped IR.

    Evidence items are dicts with keys: type, column, description.

    If required evidence is missing (e.g., an accuracy rule with no reference
    table available), returns ABSTAIN.

    Parameters
    ----------
    ir_payload:
        Scoped IR dict from scope_resolver.
    dataset_columns:
        Available column names in the dataset.
    trace_id:
        Trace identifier.
    llm_fn:
        Optional LLM function: ir_dict → list of evidence dicts.

    Returns
    -------
    AgentResult with evidence list in payload["evidence"].
    """
    tid = trace_id or new_trace_id()
    start = time.monotonic()
    agent_id = "evidence-locator-v1"
    input_hash = hash_dict(ir_payload)

    try:
        ir = IR.model_validate(ir_payload)

        if llm_fn is not None:
            evidence_items = llm_fn(ir_payload)
        else:
            # Rule-based evidence inference
            evidence_items = _infer_evidence(ir, dataset_columns or [])

        # Check for missing evidence on dimensions that require external references
        if ir.dimension in _EVIDENCE_REQUIRING_EXTERNAL_REF:
            has_external = any(
                e.get("type") in ("external_ref", "reference_table")
                for e in evidence_items
            )
            if not has_external:
                elapsed = (time.monotonic() - start) * 1000
                payload = json.loads(ir.model_dump_json())
                payload["evidence"] = evidence_items
                return AgentResult(
                    status="ABSTAIN",
                    payload=payload,
                    evidence=evidence_items,
                    diagnostics=[{
                        "level": "warning",
                        "message": (
                            f"Dimension '{ir.dimension}' requires an external reference "
                            "but none was found. Abstaining."
                        )
                    }],
                    trace_id=tid,
                    elapsed_ms=(time.monotonic() - start) * 1000,
                    agent_id=agent_id,
                    from_state=PipelineState.SCOPED,
                    to_state=PipelineState.ABSTAIN,
                    input_hash=input_hash,
                    output_hash=hash_dict({"evidence": evidence_items}),
                )

        elapsed = (time.monotonic() - start) * 1000
        payload = json.loads(ir.model_dump_json())
        payload["evidence"] = evidence_items

        return AgentResult(
            status="OK",
            payload=payload,
            evidence=evidence_items,
            diagnostics=[],
            trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
            from_state=PipelineState.SCOPED,
            to_state=PipelineState.PLANNED,
            input_hash=input_hash,
            output_hash=hash_dict({"evidence": evidence_items}),
        )

    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return AgentResult(
            status="ERROR", payload={}, evidence=[],
            diagnostics=[{"level": "error", "message": str(exc)}],
            trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
            from_state=PipelineState.SCOPED,
            to_state=PipelineState.FAILED,
            input_hash=input_hash, output_hash=hash_dict({}),
        )


def _infer_evidence(ir: IR, dataset_columns: list[str]) -> list[dict[str, Any]]:
    """Rule-based evidence inference from IR scope and columns."""
    evidence: list[dict[str, Any]] = []
    for col in ir.scope.columns:
        if col in dataset_columns:
            evidence.append({
                "type": "column_value",
                "column": col,
                "description": f"Direct value of column '{col}'",
            })
    return evidence
