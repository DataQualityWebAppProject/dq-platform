"""Test case generation for rule validation.

Generates the 5 canonical case types defined in the taxonomy:
- positive: satisfies the rule (no violation expected)
- negative: clearly violates the rule
- boundary: edge case at the constraint boundary
- ambiguous: case where the rule is unclear (expected: ABSTAIN)
- not_applicable: antecedent not met (vacuous truth / non-applicability)

Design rule: every FROZEN rule must have at least one example of each type
before it can participate in the benchmark.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from rule_corpus.taxonomy import CASE_TYPES


CaseTypeT = Literal["positive", "negative", "boundary", "ambiguous", "not_applicable"]


@dataclass
class TestCase:
    """A single test case for a rule."""
    case_type: CaseTypeT
    input_data: dict[str, Any]       # Row or group of rows as dict
    expected_label: bool | None       # True=violation, False=ok, None=ABSTAIN
    expected_state: Literal["VALIDATED", "ABSTAIN", "HUMAN_REVIEW"] = "VALIDATED"
    notes: str = ""

    def __post_init__(self) -> None:
        if self.case_type not in CASE_TYPES:
            raise ValueError(f"Invalid case_type: '{self.case_type}'. Must be one of {CASE_TYPES}.")
        # Consistency check
        if self.case_type == "ambiguous" and self.expected_state != "ABSTAIN":
            raise ValueError(
                "Ambiguous test cases must have expected_state='ABSTAIN'."
            )
        if self.case_type == "not_applicable" and self.expected_label is not None:
            raise ValueError(
                "not_applicable test cases must have expected_label=None "
                "(vacuous truth — the rule does not apply)."
            )


@dataclass
class TestCaseSet:
    """Collection of test cases for a single rule."""
    rule_id: str
    cases: list[TestCase] = field(default_factory=list)

    def add(self, case: TestCase) -> None:
        """Add a test case to the set."""
        self.cases.append(case)

    def coverage(self) -> dict[str, int]:
        """Return counts per case type."""
        counts: dict[str, int] = {ct: 0 for ct in CASE_TYPES}
        for c in self.cases:
            counts[c.case_type] = counts.get(c.case_type, 0) + 1
        return counts

    def is_complete(self) -> bool:
        """Return True if all 5 case types have at least one example."""
        cov = self.coverage()
        return all(cov[ct] > 0 for ct in CASE_TYPES)

    def missing_types(self) -> list[str]:
        """Return list of case types with zero examples."""
        cov = self.coverage()
        return [ct for ct in CASE_TYPES if cov[ct] == 0]


def make_test_case(
    case_type: CaseTypeT,
    input_data: dict[str, Any],
    expected_label: bool | None = None,
    notes: str = "",
) -> TestCase:
    """Convenience constructor for test cases with sensible defaults.

    Parameters
    ----------
    case_type:
        One of the 5 canonical case types.
    input_data:
        Row or group data as a dict.
    expected_label:
        True = violation detected, False = no violation, None = ABSTAIN.
        Automatically set for standard case types if not provided.
    notes:
        Human-readable explanation of the test case.
    """
    # Apply defaults for standard types
    if expected_label is None:
        if case_type == "positive":
            expected_label = False   # No violation
        elif case_type == "negative":
            expected_label = True    # Violation
        # boundary, ambiguous, not_applicable: None is correct

    expected_state: Literal["VALIDATED", "ABSTAIN", "HUMAN_REVIEW"] = "VALIDATED"
    if case_type == "ambiguous":
        expected_state = "ABSTAIN"

    return TestCase(
        case_type=case_type,
        input_data=input_data,
        expected_label=expected_label,
        expected_state=expected_state,
        notes=notes,
    )
