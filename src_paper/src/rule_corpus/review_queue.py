"""Rule review queue and lifecycle management.

States: DRAFT → REVIEWED → FROZEN
- DRAFT: created by generator or human; not yet reviewed
- REVIEWED: human-approved text, IR, oracle, and test cases
- FROZEN: immutable; participates in the benchmark splits

Design rules (R3):
- Automatic promotion to REVIEWED or FROZEN is FORBIDDEN.
- Only human reviewers can advance status beyond DRAFT.
- FROZEN rules cannot be modified — create a new rule_id instead.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from models.rule import RuleRecord
from models.ir import IR


class FrozenRuleModificationError(ValueError):
    """Raised when an attempt is made to modify a FROZEN rule."""


class AutomaticPromotionError(ValueError):
    """Raised when code attempts to auto-promote a rule to REVIEWED or FROZEN."""


def promote_to_reviewed(
    rule: RuleRecord,
    reviewer: str,
    reviewed_at: datetime | None = None,
) -> RuleRecord:
    """Promote a DRAFT rule to REVIEWED status.

    This function MUST be called by a human reviewer, not by automated code.
    Callers should verify that ir_gold, oracle, and test_cases are populated.

    Parameters
    ----------
    rule:
        The DRAFT rule to promote.
    reviewer:
        Username of the human reviewer.
    reviewed_at:
        Review timestamp (defaults to now UTC).

    Returns
    -------
    A new RuleRecord with status='REVIEWED'.

    Raises
    ------
    ValueError:
        If the rule is already REVIEWED or FROZEN, or if required fields are missing.
    """
    if rule.status == "FROZEN":
        raise FrozenRuleModificationError(
            f"Rule {rule.rule_id} is FROZEN and cannot be modified. "
            "Create a new rule_id for changes."
        )
    if rule.status == "REVIEWED":
        raise ValueError(f"Rule {rule.rule_id} is already REVIEWED.")
    if not rule.ir_gold:
        raise ValueError(
            f"Rule {rule.rule_id} cannot be promoted to REVIEWED: ir_gold is missing."
        )
    if not rule.oracle:
        raise ValueError(
            f"Rule {rule.rule_id} cannot be promoted to REVIEWED: oracle is missing."
        )
    ts = reviewed_at or datetime.now(timezone.utc)
    return rule.model_copy(update={
        "status": "REVIEWED",
        "reviewed_by": reviewer,
        "reviewed_at": ts,
    })


def promote_to_frozen(
    rule: RuleRecord,
) -> RuleRecord:
    """Promote a REVIEWED rule to FROZEN status.

    Only REVIEWED rules can be frozen. FROZEN rules are immutable.

    Returns
    -------
    A new RuleRecord with status='FROZEN'.
    """
    if rule.status == "FROZEN":
        raise FrozenRuleModificationError(
            f"Rule {rule.rule_id} is already FROZEN."
        )
    if rule.status == "DRAFT":
        raise ValueError(
            f"Rule {rule.rule_id} must be REVIEWED before it can be FROZEN."
        )
    # reviewed_by and reviewed_at must already be set (enforced by RuleRecord validator)
    return rule.model_copy(update={"status": "FROZEN"})


def load_rules_from_jsonl(path: str | Path) -> list[RuleRecord]:
    """Load a list of RuleRecord objects from a JSONL file."""
    records: list[RuleRecord] = []
    p = Path(path)
    if not p.exists():
        return records
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                data = json.loads(line)
                records.append(RuleRecord.model_validate(data))
            except Exception:
                continue
    return records


def save_rules_to_jsonl(rules: list[RuleRecord], path: str | Path) -> None:
    """Save a list of RuleRecord objects to a JSONL file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for rule in rules:
            fh.write(rule.model_dump_json() + "\n")


def get_queue_summary(rules: list[RuleRecord]) -> dict[str, int]:
    """Return a count of rules by status."""
    counts: dict[str, int] = {"DRAFT": 0, "REVIEWED": 0, "FROZEN": 0}
    for r in rules:
        counts[r.status] = counts.get(r.status, 0) + 1
    return counts
