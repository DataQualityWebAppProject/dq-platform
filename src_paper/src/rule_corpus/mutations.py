"""Controlled mutations of rules with provenance tracking.

Mutations create variants of rules for robustness testing. Each mutation:
- Records full provenance (source_rule_id, mutation_type, parameters).
- Produces a new DRAFT rule (never auto-promoted).
- Does not share oracle or IR with the parent — those must be independently verified.

Mutation types:
- schema_variant: change column/table names while preserving semantics
- negation: negate the rule's condition
- scope_change: change from row-level to group-level scope
- threshold_change: vary a numeric threshold by a controlled amount
- paraphrase_nl: rephrase the natural language without changing semantics

Interference test: two mutations of the same rule must produce different
predicted labels on at least one test case (otherwise they are identical).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from models.rule import RuleRecord
from rule_corpus.draft_generator import generate_draft, _next_rule_id


MutationTypeT = Literal[
    "schema_variant",
    "negation",
    "scope_change",
    "threshold_change",
    "paraphrase_nl",
]


@dataclass(frozen=True)
class MutationProvenance:
    """Records the origin of a mutated rule."""
    source_rule_id: str
    mutation_type: MutationTypeT
    parameters: dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_rule_id": self.source_rule_id,
            "mutation_type": self.mutation_type,
            "parameters": self.parameters,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class MutationResult:
    """A mutated rule with its provenance."""
    rule: RuleRecord
    provenance: MutationProvenance


class InterferenceError(ValueError):
    """Raised when two mutations of the same rule produce identical outputs."""


def mutate_schema_variant(
    source: RuleRecord,
    column_mapping: dict[str, str],
    new_rule_id: str | None = None,
    existing_ids: list[str] | None = None,
) -> MutationResult:
    """Create a schema variant by renaming columns in the NL text.

    Parameters
    ----------
    source:
        The original rule (must be DRAFT or REVIEWED).
    column_mapping:
        Dict mapping original column names to new names.
    new_rule_id:
        Explicit ID for the new rule; auto-generated if None.
    existing_ids:
        List of existing rule IDs for auto-generation.

    Returns
    -------
    MutationResult with a DRAFT rule and full provenance.
    """
    nl = source.nl_text
    for old, new in column_mapping.items():
        nl = nl.replace(old, new)

    rule_id = new_rule_id or _next_rule_id(existing_ids or [source.rule_id])

    new_rule = generate_draft(
        dataset_id=source.dataset_id,
        nl_text=nl,
        dimension_hint=source.dimension,
        complexity_hint=source.complexity,
        existing_rule_ids=[source.rule_id] + (existing_ids or []),
    )
    # Override rule_id to the one we computed
    new_rule = new_rule.model_copy(update={"rule_id": rule_id})

    provenance = MutationProvenance(
        source_rule_id=source.rule_id,
        mutation_type="schema_variant",
        parameters={"column_mapping": column_mapping},
    )
    return MutationResult(rule=new_rule, provenance=provenance)


def mutate_paraphrase_nl(
    source: RuleRecord,
    new_nl_text: str,
    new_rule_id: str | None = None,
    existing_ids: list[str] | None = None,
) -> MutationResult:
    """Create a paraphrase variant with a rephrased NL description.

    The semantics must be preserved — different wording, same meaning.

    Parameters
    ----------
    source:
        The original rule.
    new_nl_text:
        Rephrased NL text (same semantics as source.nl_text).
    """
    rule_id = new_rule_id or _next_rule_id([source.rule_id] + (existing_ids or []))
    new_rule = generate_draft(
        dataset_id=source.dataset_id,
        nl_text=new_nl_text,
        dimension_hint=source.dimension,
        complexity_hint=source.complexity,
        existing_rule_ids=[source.rule_id] + (existing_ids or []),
    )
    new_rule = new_rule.model_copy(update={"rule_id": rule_id})

    provenance = MutationProvenance(
        source_rule_id=source.rule_id,
        mutation_type="paraphrase_nl",
        parameters={"original_nl": source.nl_text},
    )
    return MutationResult(rule=new_rule, provenance=provenance)


def check_interference(
    mutations: list[MutationResult],
    test_inputs: list[dict[str, Any]],
    evaluate_fn: Any,  # Callable[[RuleRecord, dict], bool | None]
) -> list[tuple[int, int]]:
    """Check that no two mutations produce identical outputs on all test inputs.

    Parameters
    ----------
    mutations:
        List of MutationResult objects to compare.
    test_inputs:
        List of input dicts to evaluate each mutation on.
    evaluate_fn:
        A function (rule, input) -> bool | None that evaluates a rule.

    Returns
    -------
    List of (i, j) pairs where mutations[i] and mutations[j] are identical.
    Callers should treat this as a warning; identical pairs may indicate
    the mutation was ineffective.
    """
    if len(mutations) < 2:
        return []

    outputs: list[list[bool | None]] = []
    for m in mutations:
        row_outputs = [evaluate_fn(m.rule, inp) for inp in test_inputs]
        outputs.append(row_outputs)

    identical_pairs: list[tuple[int, int]] = []
    for i in range(len(outputs)):
        for j in range(i + 1, len(outputs)):
            if outputs[i] == outputs[j]:
                identical_pairs.append((i, j))
    return identical_pairs
