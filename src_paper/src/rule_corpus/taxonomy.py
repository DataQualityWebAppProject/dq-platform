"""Taxonomy of rule dimensions, complexity levels, logical operators,
scope levels, evidence types, and action modes for the NLQ benchmark.

This module defines the canonical controlled vocabularies used across
RuleRecord, IR, and the rule review pipeline.
"""
from __future__ import annotations

from typing import Literal


# ---------------------------------------------------------------------------
# Dimension: which data quality aspect the rule targets
# ---------------------------------------------------------------------------

DimensionT = Literal[
    "completeness",   # Missing values, null rates, required fields
    "validity",       # Domain constraints, type checks, format rules
    "consistency",    # Cross-field or cross-table logical constraints
    "uniqueness",     # Duplicate detection at row or key level
    "accuracy",       # Conformance to a reference source
    "timeliness",     # Freshness, recency, temporal validity
]

DIMENSIONS: tuple[str, ...] = (
    "completeness", "validity", "consistency",
    "uniqueness", "accuracy", "timeliness",
)

DIMENSION_DESCRIPTIONS: dict[str, str] = {
    "completeness": "Missing values, null rates, required fields present.",
    "validity": "Domain constraints, type checks, enumerated values, format patterns.",
    "consistency": "Logical constraints across fields, records, or tables.",
    "uniqueness": "Duplicate detection at record, key, or attribute level.",
    "accuracy": "Conformance to an authoritative external reference source.",
    "timeliness": "Data freshness, recency windows, temporal ordering constraints.",
}


# ---------------------------------------------------------------------------
# Complexity: determines which pipeline path the rule takes
# ---------------------------------------------------------------------------

ComplexityT = Literal[
    "POINT_IN_TIME",   # Rule evaluated independently on each row/record
    "HISTORICAL",      # Rule requires comparing values across time
    "ML_NECESSARY",    # Rule requires ML model prediction to evaluate
    "ABSTAIN",         # Rule is too ambiguous or complex to process
]

COMPLEXITY_DESCRIPTIONS: dict[str, str] = {
    "POINT_IN_TIME": "Evaluated on each row independently; no history needed.",
    "HISTORICAL": "Requires comparing values across time windows or previous states.",
    "ML_NECESSARY": "Cannot be evaluated with deterministic logic; requires ML inference.",
    "ABSTAIN": "Rule is ambiguous or underspecified; requires human clarification.",
}


# ---------------------------------------------------------------------------
# Logical operators: used in IRLogic.operator
# ---------------------------------------------------------------------------

LogicOperatorT = Literal[
    "AND",      # All sub-conditions must hold
    "OR",       # At least one sub-condition must hold
    "NOT",      # Negation of a sub-condition
    "IF",       # Conditional (implication): IF antecedent THEN consequent
    "IFF",      # Biconditional: IF AND ONLY IF (both directions)
    "FORALL",   # Universal quantification over a collection
    "EXISTS",   # Existential quantification over a collection
    "NONE",     # No logical structure (atomic rule)
]

LOGIC_OPERATOR_DESCRIPTIONS: dict[str, str] = {
    "AND": "Conjunction: all clauses must hold simultaneously.",
    "OR": "Disjunction: at least one clause must hold.",
    "NOT": "Negation: the clause must NOT hold.",
    "IF": "Implication: if the antecedent holds, the consequent must hold.",
    "IFF": "Biconditional: the antecedent holds if and only if the consequent holds.",
    "FORALL": "Universal quantifier: the condition must hold for ALL elements.",
    "EXISTS": "Existential quantifier: the condition must hold for AT LEAST ONE element.",
    "NONE": "Atomic rule with no explicit logical structure.",
}

# Operators that require exactly two clauses
BINARY_OPERATORS: frozenset[str] = frozenset({"AND", "OR", "IF", "IFF"})

# Operators that require exactly one clause
UNARY_OPERATORS: frozenset[str] = frozenset({"NOT", "FORALL", "EXISTS"})


# ---------------------------------------------------------------------------
# Scope levels: what the rule applies to
# ---------------------------------------------------------------------------

ScopeLevelT = Literal[
    "row",         # Single row evaluation
    "group",       # Group of rows (e.g., by customer ID)
    "table",       # Entire table aggregate
    "cross_table", # Multiple tables involved
]

SCOPE_LEVEL_DESCRIPTIONS: dict[str, str] = {
    "row": "Each row is evaluated independently.",
    "group": "Groups of rows (e.g., all orders for one customer) are evaluated together.",
    "table": "The entire table is aggregated for evaluation.",
    "cross_table": "Rule involves joining or comparing multiple tables.",
}


# ---------------------------------------------------------------------------
# Evidence types: what kind of evidence is needed
# ---------------------------------------------------------------------------

EVIDENCE_TYPES: tuple[str, ...] = (
    "column_value",    # Direct column value comparison
    "aggregate",       # COUNT, SUM, AVG, etc. over rows
    "reference_table", # Join to a reference / lookup table
    "time_window",     # Values within a time range
    "external_ref",    # External authoritative source
    "ml_score",        # ML model prediction score
)


# ---------------------------------------------------------------------------
# Action modes: what the rule does when a violation is detected
# ---------------------------------------------------------------------------

ActionModeT = Literal[
    "detect",  # Flag the violating rows / records
    "repair",  # Propose a corrected value
    "flag",    # Mark for human review
    "abstain", # Cannot determine; escalate to HUMAN_REVIEW
]

ACTION_MODE_DESCRIPTIONS: dict[str, str] = {
    "detect": "Flag rows/records that violate the rule.",
    "repair": "Detect and propose a corrected value for the violation.",
    "flag": "Mark for human review without a definitive verdict.",
    "abstain": "The system cannot determine the verdict; escalate to HUMAN_REVIEW.",
}


# ---------------------------------------------------------------------------
# Rule case types: for test case generation
# ---------------------------------------------------------------------------

CASE_TYPES: tuple[str, ...] = (
    "positive",    # Example that satisfies the rule (no violation)
    "negative",    # Example that clearly violates the rule
    "boundary",    # Edge case at the boundary of the constraint
    "ambiguous",   # Case where the rule is unclear (should yield ABSTAIN)
    "not_applicable", # Case where the rule's antecedent is not met (vacuous truth)
)
