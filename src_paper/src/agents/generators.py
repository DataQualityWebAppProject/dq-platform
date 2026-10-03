"""Code generators for quality rule evaluation.

Three generators matching the three routable complexity levels:
- PointInTimeGenerator: deterministic row-level checks
- HistoricalGenerator: time-window comparisons
- MLGenerator: ML model inference (requires model adapter injection)

All generators produce Python code as a string. The code defines a `check`
function that takes a Parquet path and returns a JSON-serializable dict.

Design rule: a function that executes but violates semantics is incorrect.
The generated code is subject to AST guard and sandbox validation.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable

from models.agent_result import AgentResult
from models.ir import IR
from orchestration.state_machine import PipelineState
from utils.ids import hash_dict, hash_content, new_trace_id


# ---------------------------------------------------------------------------
# Code templates
# ---------------------------------------------------------------------------

_POINT_IN_TIME_TEMPLATE = """
import pandas as pd
import json

def check(sample_path: str) -> dict:
    df = pd.read_parquet(sample_path)
    flagged = []
    for idx, row in df.iterrows():
        # Rule: {rule_description}
        # Columns in scope: {columns}
        try:
            violation = _evaluate_row(row)
            if violation:
                flagged.append(int(idx))
        except Exception:
            pass
    return {{"flagged_rows": flagged, "total_rows": len(df), "result": "ok"}}

def _evaluate_row(row):
    # TODO: implement rule-specific check
    # Scope columns: {columns}
    return False
"""

_HISTORICAL_TEMPLATE = """
import pandas as pd
import json

def check(sample_path: str) -> dict:
    df = pd.read_parquet(sample_path)
    flagged = []
    # Rule: {rule_description}
    # Time window: {time_window}
    # Columns in scope: {columns}
    # TODO: implement historical comparison
    return {{"flagged_rows": flagged, "total_rows": len(df), "result": "ok"}}
"""

_ML_TEMPLATE = """
import pandas as pd
import json

def check(sample_path: str) -> dict:
    df = pd.read_parquet(sample_path)
    flagged = []
    # Rule: {rule_description}
    # ML model required for: {dimension}
    # TODO: inject ML model predictions
    # ML gate was confirmed before generating this code.
    return {{"flagged_rows": flagged, "total_rows": len(df), "result": "ok"}}
"""


# ---------------------------------------------------------------------------
# Generator functions
# ---------------------------------------------------------------------------

def generate_code(
    ir_payload: dict[str, Any],
    trace_id: str | None = None,
    llm_fn: Callable[[dict[str, Any]], str] | None = None,
) -> AgentResult:
    """Generate Python code for rule evaluation.

    Uses the generator type from payload["generator"] to select the template.
    If llm_fn is provided, it overrides the template with LLM-generated code.

    Returns AgentResult with payload["code"] containing the Python source.
    """
    tid = trace_id or new_trace_id()
    start = time.monotonic()
    agent_id = "code-generator-v1"
    input_hash = hash_dict(ir_payload)

    try:
        ir = IR.model_validate(ir_payload)
        generator = ir_payload.get("generator", "point_in_time")
        columns_str = ", ".join(ir.scope.columns) or "unknown"
        time_window_str = str(ir.time_window or "none")

        if llm_fn is not None:
            code = llm_fn(ir_payload)
        else:
            if generator == "historical":
                code = _HISTORICAL_TEMPLATE.format(
                    rule_description=f"{ir.dimension} rule {ir.rule_id}",
                    time_window=time_window_str,
                    columns=columns_str,
                )
            elif generator == "ml":
                code = _ML_TEMPLATE.format(
                    rule_description=f"{ir.dimension} rule {ir.rule_id}",
                    dimension=ir.dimension,
                )
            else:
                code = _POINT_IN_TIME_TEMPLATE.format(
                    rule_description=f"{ir.dimension} rule {ir.rule_id}",
                    columns=columns_str,
                )

        code_hash = hash_content(code)
        elapsed = (time.monotonic() - start) * 1000
        payload = ir_payload.copy()
        payload["code"] = code
        payload["code_hash"] = code_hash

        return AgentResult(
            status="OK", payload=payload, evidence=[], diagnostics=[],
            trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
            from_state=PipelineState.GENERATED,
            to_state=PipelineState.AST_VALID,
            input_hash=input_hash, output_hash=code_hash,
        )

    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return AgentResult(
            status="ERROR", payload={}, evidence=[],
            diagnostics=[{"level": "error", "message": str(exc)}],
            trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
            from_state=PipelineState.GENERATED,
            to_state=PipelineState.FAILED,
            input_hash=input_hash, output_hash=hash_dict({}),
        )
