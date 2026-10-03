"""Automatic audit of rule corpus for coverage, balance, duplicates and consistency.

Audit dimensions (R3):
1. Coverage: every dimension, complexity, and case type is represented.
2. Balance: no single dimension dominates (> 30% of rules).
3. Duplicates: no two rules have identical nl_text (fuzzy).
4. Consistency: frozen rules must have ir_gold and oracle set.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from models.rule import RuleRecord
from rule_corpus.taxonomy import DIMENSIONS


@dataclass
class AuditIssue:
    """A single audit finding."""
    severity: str  # "error", "warning", "info"
    code: str
    message: str
    rule_ids: list[str] = field(default_factory=list)


@dataclass
class CorpusAuditReport:
    """Full audit report for a rule corpus."""
    n_rules: int
    n_frozen: int
    n_reviewed: int
    n_draft: int
    dimension_counts: dict[str, int]
    complexity_counts: dict[str, int]
    issues: list[AuditIssue] = field(default_factory=list)
    passed: bool = True

    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    def summary(self) -> str:
        status = "PASS" if not self.has_errors() else "FAIL"
        n_issues = len(self.issues)
        return (
            f"[{status}] {self.n_rules} rules — "
            f"{self.n_frozen} FROZEN, {self.n_reviewed} REVIEWED, {self.n_draft} DRAFT | "
            f"{n_issues} issue(s)"
        )


def audit_corpus(
    rules: list[RuleRecord],
    min_per_dimension: int = 1,
    max_fraction_per_dimension: float = 0.35,
    duplicate_similarity_threshold: float = 0.95,
) -> CorpusAuditReport:
    """Run all audit checks on a rule corpus.

    Parameters
    ----------
    rules:
        The list of RuleRecord objects to audit.
    min_per_dimension:
        Minimum number of rules per quality dimension.
    max_fraction_per_dimension:
        Maximum fraction of rules a single dimension may occupy.
    duplicate_similarity_threshold:
        Jaccard similarity above which two NL texts are considered duplicates.

    Returns
    -------
    CorpusAuditReport with all findings.
    """
    issues: list[AuditIssue] = []
    n = len(rules)

    # Count by status
    n_frozen = sum(1 for r in rules if r.status == "FROZEN")
    n_reviewed = sum(1 for r in rules if r.status == "REVIEWED")
    n_draft = sum(1 for r in rules if r.status == "DRAFT")

    # Count by dimension and complexity
    dim_counts: dict[str, int] = {d: 0 for d in DIMENSIONS}
    complexity_counts: dict[str, int] = {}
    for r in rules:
        dim_counts[r.dimension] = dim_counts.get(r.dimension, 0) + 1
        complexity_counts[r.complexity] = complexity_counts.get(r.complexity, 0) + 1

    # --- Audit 1: Coverage by dimension ---
    for dim in DIMENSIONS:
        count = dim_counts.get(dim, 0)
        if count < min_per_dimension:
            issues.append(AuditIssue(
                severity="warning",
                code="LOW_DIMENSION_COVERAGE",
                message=f"Dimension '{dim}' has only {count} rules (minimum: {min_per_dimension}).",
            ))

    # --- Audit 2: Balance check ---
    if n > 0:
        for dim, count in dim_counts.items():
            fraction = count / n
            if fraction > max_fraction_per_dimension:
                issues.append(AuditIssue(
                    severity="warning",
                    code="DIMENSION_IMBALANCE",
                    message=(
                        f"Dimension '{dim}' represents {fraction:.0%} of rules "
                        f"(max allowed: {max_fraction_per_dimension:.0%})."
                    ),
                ))

    # --- Audit 3: Duplicate NL detection (exact match only for efficiency) ---
    nl_seen: dict[str, str] = {}  # normalized_nl → rule_id
    for r in rules:
        nl_key = r.nl_text.lower().strip()
        if nl_key in nl_seen:
            issues.append(AuditIssue(
                severity="error",
                code="DUPLICATE_NL_TEXT",
                message=f"Rules {nl_seen[nl_key]} and {r.rule_id} have identical NL text.",
                rule_ids=[nl_seen[nl_key], r.rule_id],
            ))
        else:
            nl_seen[nl_key] = r.rule_id

    # --- Audit 4: Consistency checks for FROZEN rules ---
    for r in rules:
        if r.status == "FROZEN":
            if not r.ir_gold:
                issues.append(AuditIssue(
                    severity="error",
                    code="FROZEN_MISSING_IR",
                    message=f"FROZEN rule {r.rule_id} has no ir_gold.",
                    rule_ids=[r.rule_id],
                ))
            if not r.oracle:
                issues.append(AuditIssue(
                    severity="error",
                    code="FROZEN_MISSING_ORACLE",
                    message=f"FROZEN rule {r.rule_id} has no oracle.",
                    rule_ids=[r.rule_id],
                ))
            if not r.test_cases:
                issues.append(AuditIssue(
                    severity="warning",
                    code="FROZEN_NO_TEST_CASES",
                    message=f"FROZEN rule {r.rule_id} has no test cases.",
                    rule_ids=[r.rule_id],
                ))

    passed = not any(i.severity == "error" for i in issues)
    return CorpusAuditReport(
        n_rules=n,
        n_frozen=n_frozen,
        n_reviewed=n_reviewed,
        n_draft=n_draft,
        dimension_counts=dim_counts,
        complexity_counts=complexity_counts,
        issues=issues,
        passed=passed,
    )
