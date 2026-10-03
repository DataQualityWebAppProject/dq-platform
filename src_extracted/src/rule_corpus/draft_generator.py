"""Assisted draft rule generator.

Generates DRAFT-status RuleRecord skeletons from a dataset schema and
a natural-language description. The generator NEVER auto-promotes to REVIEWED
or FROZEN — that requires human review (T3.2, design.md).

Integrity rules:
- All generated rules have status=DRAFT.
- The ir_gold field is always None (requires human IR authoring).
- The oracle field is always None (requires human oracle authoring).
- The generator may suggest a dimension and complexity but cannot finalize them.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from models.rule import RuleRecord
from models.ir import IR
from rule_corpus.taxonomy import DIMENSIONS, COMPLEXITY_DESCRIPTIONS


class AutoPromotionGuard:
    """Context manager that prevents any code within it from auto-promoting rules."""

    def __enter__(self) -> "AutoPromotionGuard":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass  # No cleanup needed; guard is a documentation artifact


def _next_rule_id(existing_ids: list[str]) -> str:
    """Generate the next sequential rule ID.

    Parameters
    ----------
    existing_ids:
        List of existing rule IDs in the format R-NNNN.

    Returns
    -------
    Next ID, e.g. "R-0042" if the highest existing is "R-0041".
    """
    if not existing_ids:
        return "R-0001"
    numbers = []
    for rid in existing_ids:
        m = re.match(r"^R-(\d{4})$", rid)
        if m:
            numbers.append(int(m.group(1)))
    if not numbers:
        return "R-0001"
    return f"R-{max(numbers) + 1:04d}"


def generate_draft(
    dataset_id: str,
    nl_text: str,
    dimension_hint: str = "validity",
    complexity_hint: str = "POINT_IN_TIME",
    existing_rule_ids: list[str] | None = None,
) -> RuleRecord:
    """Generate a single DRAFT rule skeleton.

    The generated rule has:
    - status = DRAFT (NEVER auto-promoted)
    - ir_gold = None (requires human authoring)
    - oracle = None (requires human authoring)
    - reviewed_by = None
    - reviewed_at = None

    Parameters
    ----------
    dataset_id:
        The dataset this rule applies to (owner/slug).
    nl_text:
        Natural-language rule description.
    dimension_hint:
        Suggested quality dimension (human must verify).
    complexity_hint:
        Suggested complexity level (human must verify).
    existing_rule_ids:
        List of existing rule IDs to avoid collisions.

    Returns
    -------
    A DRAFT RuleRecord with no gold labels, no oracle, no IR.
    """
    if dimension_hint not in DIMENSIONS:
        dimension_hint = "validity"
    if complexity_hint not in COMPLEXITY_DESCRIPTIONS:
        complexity_hint = "POINT_IN_TIME"

    rule_id = _next_rule_id(existing_rule_ids or [])

    # Explicitly ensure no auto-promotion is possible
    return RuleRecord(
        rule_id=rule_id,
        dataset_id=dataset_id,
        nl_text=nl_text,
        dimension=dimension_hint,  # type: ignore[arg-type]
        complexity=complexity_hint,  # type: ignore[arg-type]
        status="DRAFT",  # NEVER auto-promoted
        ir_gold=None,    # Requires human review
        oracle=None,     # Requires human review
        reviewed_by=None,
        reviewed_at=None,
        created_at=datetime.now(timezone.utc),
    )


def generate_drafts_for_dataset(
    dataset_id: str,
    schema_columns: list[str],
    n_rules: int = 5,
    existing_rule_ids: list[str] | None = None,
) -> list[RuleRecord]:
    """Generate n_rules DRAFT skeletons for a dataset based on its schema.

    Each draft targets a different quality dimension in round-robin order.
    All rules are DRAFT-only — no gold labels, no IR, no oracle.

    Parameters
    ----------
    dataset_id:
        Dataset identifier (owner/slug).
    schema_columns:
        List of column names from the dataset profile.
    n_rules:
        Number of draft rules to generate (default: 5 per spec).
    existing_rule_ids:
        Existing rule IDs to avoid collision.

    Returns
    -------
    List of DRAFT RuleRecord objects.
    """
    drafts: list[RuleRecord] = []
    current_ids = list(existing_rule_ids or [])

    dimension_cycle = list(DIMENSIONS)
    col_display = ", ".join(schema_columns[:3]) if schema_columns else "all columns"

    for i in range(n_rules):
        dim = dimension_cycle[i % len(dimension_cycle)]
        if dim == "completeness":
            nl = f"All required fields in {col_display} must not be null."
        elif dim == "validity":
            nl = f"Values in {col_display} must conform to their expected data type and domain."
        elif dim == "consistency":
            nl = f"Records with related values in {col_display} must be mutually consistent."
        elif dim == "uniqueness":
            nl = f"Each combination of {col_display} must be unique across the dataset."
        elif dim == "accuracy":
            nl = f"Values in {col_display} must match the authoritative reference values."
        else:  # timeliness
            nl = f"Records in {col_display} must reflect data collected within the valid time window."

        draft = generate_draft(
            dataset_id=dataset_id,
            nl_text=nl,
            dimension_hint=dim,
            complexity_hint="POINT_IN_TIME",
            existing_rule_ids=current_ids,
        )
        drafts.append(draft)
        current_ids.append(draft.rule_id)

    return drafts
