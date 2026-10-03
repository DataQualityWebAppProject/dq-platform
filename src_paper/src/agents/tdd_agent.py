"""TDD Agent (T4.6) — Generates >= 3 executable test cases from IR BEFORE code generation.

Property P8: minimum 3 test cases always.
  - positive: a row that VIOLATES the rule (must be detected)
  - negative: a correct row (must NOT be detected)
  - null_safe: a row with null in the target column (must not crash)

The tests are Python code, not documentation. They are passed to the CodeGenerator
as executable constraints. If the generated code fails any test, the RepairAgent
receives the exact failure.

Design rule: tests are derived from the IR logic, not from the NL text.
This prevents circular reasoning (generating code that matches words, not semantics).
"""
from __future__ import annotations

import json
import textwrap
import time
from typing import Any

from models.agent_result import AgentResult
from models.ir import IR
from orchestration.state_machine import PipelineState
from utils.ids import hash_dict, new_trace_id


def generate_tdd_tests(
    ir_payload: dict[str, Any],
    dataset_columns: list[str] | None = None,
    trace_id: str | None = None,
) -> AgentResult:
    """Generate >= 3 executable test cases from the IR.

    Parameters
    ----------
    ir_payload:
        The planned IR dict (from LogicalPlanner).
    dataset_columns:
        Available column names in the dataset (for realistic test data).
    trace_id:
        Trace identifier.

    Returns
    -------
    AgentResult with payload["tdd_tests"] = list of test dicts and
    payload["test_code"] = executable Python test function string.
    """
    tid = trace_id or new_trace_id()
    start = time.monotonic()
    agent_id = "tdd-agent-v1"
    input_hash = hash_dict(ir_payload)

    try:
        ir = IR.model_validate(ir_payload)
        tests = _generate_from_ir(ir, dataset_columns or [])

        if len(tests) < 3:
            elapsed = (time.monotonic() - start) * 1000
            return AgentResult(
                status="HUMAN_REVIEW",
                payload={"tdd_tests": tests, "test_code": ""},
                evidence=[],
                diagnostics=[{
                    "level": "error",
                    "message": f"P8 violated: only {len(tests)} tests generated (minimum 3)."
                }],
                trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
                from_state=PipelineState.ROUTED,
                to_state=PipelineState.HUMAN_REVIEW,
                input_hash=input_hash, output_hash=hash_dict({}),
            )

        test_code = _render_test_function(tests, ir)
        elapsed = (time.monotonic() - start) * 1000

        return AgentResult(
            status="OK",
            payload={
                "tdd_tests": tests,
                "test_code": test_code,
                "n_tests": len(tests),
            },
            evidence=[],
            diagnostics=[{"level": "info", "message": f"Generated {len(tests)} tests (P8 satisfied)."}],
            trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
            from_state=PipelineState.ROUTED,
            to_state="TESTED_SPEC",
            input_hash=input_hash, output_hash=hash_dict({"n_tests": len(tests)}),
        )

    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return AgentResult(
            status="ERROR",
            payload={},
            evidence=[],
            diagnostics=[{"level": "error", "message": str(exc)}],
            trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
            from_state=PipelineState.ROUTED,
            to_state=PipelineState.FAILED,
            input_hash=input_hash, output_hash=hash_dict({}),
        )


def _generate_from_ir(ir: IR, columns: list[str]) -> list[dict]:
    """Generate test cases by inspecting the IR logic clauses."""
    tests = []
    operator = ir.logic.operator
    clauses = ir.logic.clauses
    target_cols = ir.scope.columns or columns[:1] or ["value"]

    # --- Positive test: build a row that VIOLATES the rule ---
    positive_row = _build_violating_row(operator, clauses, target_cols)
    tests.append({
        "case_type": "positive",
        "description": "Row that violates the rule — must be detected (expected_violation=True)",
        "input_row": positive_row,
        "expected_violation": True,
    })

    # --- Negative test: build a row that SATISFIES the rule ---
    negative_row = _build_satisfying_row(operator, clauses, target_cols)
    tests.append({
        "case_type": "negative",
        "description": "Correct row — must NOT be detected (expected_violation=False)",
        "input_row": negative_row,
        "expected_violation": False,
    })

    # --- Null-safe test: target column is null ---
    null_row = {col: None for col in target_cols}
    for col in columns:
        if col not in null_row:
            null_row[col] = "placeholder"
    tests.append({
        "case_type": "null_safe",
        "description": "Row with null in target columns — must not crash",
        "input_row": null_row,
        "expected_violation": None,  # null = non-applicable, system must not raise
    })

    # --- Non-applicability test (if trigger exists) ---
    if ir.non_applicability and ir.non_applicability.get("condition"):
        na_row = _build_non_applicable_row(ir, target_cols, columns)
        tests.append({
            "case_type": "not_applicable",
            "description": "Row where the rule antecedent is not met — should be ABSTAIN or not flagged",
            "input_row": na_row,
            "expected_violation": False,  # vacuous truth: non-applicable = not a violation
        })

    # --- Boundary test (for range clauses) ---
    boundary_row = _build_boundary_row(clauses, target_cols, columns)
    if boundary_row:
        tests.append({
            "case_type": "boundary",
            "description": "Row exactly at the boundary of the constraint",
            "input_row": boundary_row,
            "expected_violation": False,
        })

    return tests


def _build_violating_row(operator: str, clauses: list[dict], target_cols: list[str]) -> dict:
    """Build a row that violates the rule by inverting the conditions."""
    row: dict[str, Any] = {}
    for col in target_cols:
        row[col] = _violating_value(clauses, col)
    return row


def _build_satisfying_row(operator: str, clauses: list[dict], target_cols: list[str]) -> dict:
    """Build a row that satisfies the rule."""
    row: dict[str, Any] = {}
    for col in target_cols:
        row[col] = _satisfying_value(clauses, col)
    return row


def _build_non_applicable_row(ir: IR, target_cols: list[str], all_cols: list[str]) -> dict:
    """Build a row where the antecedent (trigger) is not met."""
    row: dict[str, Any] = {}
    # Invert trigger condition
    trigger = ir.trigger or {}
    trigger_col = trigger.get("field", "")
    trigger_val = trigger.get("value", "other")
    if trigger_col:
        row[trigger_col] = f"NOT_{trigger_val}"
    for col in target_cols:
        if col not in row:
            row[col] = 100  # valid value for the target
    return row


def _build_boundary_row(clauses: list[dict], target_cols: list[str], all_cols: list[str]) -> dict | None:
    """Build a row exactly at the boundary of range constraints."""
    for clause in clauses:
        op = clause.get("op", "")
        field = clause.get("field", "")
        value = clause.get("value")
        if field in target_cols and value is not None:
            if op == "gte":
                return {field: value}  # exactly at minimum
            elif op == "lte":
                return {field: value}  # exactly at maximum
            elif op == "gt":
                return {field: value + (1 if isinstance(value, (int, float)) else 0)}
            elif op == "lt":
                return {field: value - (1 if isinstance(value, (int, float)) else 0)}
    return None


def _violating_value(clauses: list[dict], col: str) -> Any:
    """Return a value that violates constraints for this column."""
    for clause in clauses:
        if clause.get("field") == col:
            op = clause.get("op", "")
            val = clause.get("value")
            if op in ("not_null", "is_not_null"):
                return None
            if op in ("gt", "gte") and isinstance(val, (int, float)):
                return val - 100  # clearly below minimum
            if op in ("lt", "lte") and isinstance(val, (int, float)):
                return val + 100  # clearly above maximum
            if op == "in" and isinstance(val, list):
                return "INVALID_VALUE_NOT_IN_LIST"
            if op == "matches_regex":
                return "!!!INVALID FORMAT!!!"
            if op == "unique_in_dataset":
                return "DUPLICATE_VALUE"
    return -9999  # generic violating value


def _satisfying_value(clauses: list[dict], col: str) -> Any:
    """Return a value that satisfies constraints for this column."""
    for clause in clauses:
        if clause.get("field") == col:
            op = clause.get("op", "")
            val = clause.get("value")
            if op in ("not_null", "is_not_null"):
                return 42
            if op in ("gt", "gte") and isinstance(val, (int, float)):
                return val + 10  # clearly above minimum
            if op in ("lt", "lte") and isinstance(val, (int, float)):
                return val - 10  # clearly below maximum
            if op == "in" and isinstance(val, list) and len(val) > 0:
                return val[0]  # first valid value
            if op == "matches_regex":
                return "AB"  # generic valid format
            if op == "unique_in_dataset":
                return "UNIQUE_ID_12345"
    return 100  # generic satisfying value


def _render_test_function(tests: list[dict], ir: IR) -> str:
    """Render tests as an executable Python function for use in prompts."""
    lines = [
        "import pandas as pd",
        "",
        f"# TDD tests for rule {ir.rule_id} ({ir.dimension}, {ir.complexity})",
        "# These tests must ALL pass for the generated check(df) to be accepted.",
        "",
        "def run_tdd_tests(check_fn):",
        '    """Run P8 tests. Returns (passed, failed_descriptions)."""',
        "    passed = []",
        "    failed = []",
        "",
    ]
    for i, test in enumerate(tests):
        case_type = test["case_type"]
        row = test["input_row"]
        expected = test["expected_violation"]
        desc = test["description"]

        lines.append(f"    # Test {i+1}: {case_type} — {desc}")
        lines.append(f"    row_{i} = {json.dumps(row)}")
        lines.append(f"    df_{i} = pd.DataFrame([row_{i}])")
        lines.append(f"    try:")
        lines.append(f"        result_{i} = check_fn(df_{i})")

        if expected is None:
            # null-safe: just must not raise
            lines.append(f"        passed.append('test_{i+1}_{case_type}')")
        elif expected:
            # must be detected (index 0 must be in result)
            lines.append(f"        if 0 in result_{i}:")
            lines.append(f"            passed.append('test_{i+1}_{case_type}')")
            lines.append(f"        else:")
            lines.append(f"            failed.append('test_{i+1}_{case_type}: expected row 0 to be flagged')")
        else:
            # must NOT be detected
            lines.append(f"        if 0 not in result_{i}:")
            lines.append(f"            passed.append('test_{i+1}_{case_type}')")
            lines.append(f"        else:")
            lines.append(f"            failed.append('test_{i+1}_{case_type}: expected row 0 NOT to be flagged')")

        lines.append(f"    except Exception as e:")
        if expected is None:
            lines.append(f"        failed.append(f'test_{i+1}_{case_type}: crashed — {{e}}')")
        else:
            lines.append(f"        failed.append(f'test_{i+1}_{case_type}: raised {{e}}')")
        lines.append("")

    lines.extend([
        "    return passed, failed",
        "",
        "# Quick validation",
        "# passed, failed = run_tdd_tests(check)",
        "# assert len(failed) == 0, f'TDD failures: {failed}'",
    ])
    return "\n".join(lines)
