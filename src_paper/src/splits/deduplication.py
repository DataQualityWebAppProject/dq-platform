"""Deduplication of datasets, schemas, families, rules and IR.

Partition unit: dataset/family, NEVER an individual paraphrase.
All paraphrases and mutations of a rule must stay in the same split.

Design rules (R12):
- No two families can span train and test.
- Schema-similar datasets are treated as the same family.
- Duplicate NL texts are removed before split creation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from data_registry.deduplicator import detect_duplicates, DuplicateResult


@dataclass
class DeduplicationReport:
    """Report of deduplications applied before split creation."""
    n_input_datasets: int
    n_output_datasets: int
    n_input_rules: int
    n_output_rules: int
    duplicate_dataset_pairs: list[DuplicateResult]
    duplicate_rule_ids: list[tuple[str, str]]   # (rule_id_a, rule_id_b)
    removed_dataset_ids: list[str]
    removed_rule_ids: list[str]
    family_groups: dict[str, list[str]]  # family_key → list of dataset_ids


def deduplicate_datasets(
    registry: list[dict[str, Any]],
    schema_similarity_threshold: float = 0.8,
) -> tuple[list[dict[str, Any]], DeduplicationReport]:
    """Remove duplicate datasets from the registry.

    Parameters
    ----------
    registry:
        List of dataset metadata dicts with keys: dataset_id, sha256_files, column_names.
    schema_similarity_threshold:
        Jaccard similarity above which two datasets are treated as the same family.

    Returns
    -------
    (deduplicated_registry, report)
    """
    duplicates = detect_duplicates(registry, schema_similarity_threshold)

    # Build family groups: datasets in the same family are grouped together
    family_map: dict[str, str] = {}  # dataset_id → canonical_family_id
    for dup in duplicates:
        family_a = family_map.get(dup.dataset_id_a, dup.dataset_id_a)
        family_map[dup.dataset_id_b] = family_a

    # Remove exact duplicates (keep first occurrence)
    seen_ids: set[str] = set()
    removed_ids: list[str] = []
    kept: list[dict[str, Any]] = []
    for entry in registry:
        did = entry["dataset_id"]
        canonical = family_map.get(did, did)
        if canonical in seen_ids and canonical != did:
            removed_ids.append(did)
        else:
            seen_ids.add(did)
            kept.append(entry)

    # Build family groups output
    family_groups: dict[str, list[str]] = {}
    for did in [e["dataset_id"] for e in registry]:
        fam = family_map.get(did, did)
        family_groups.setdefault(fam, []).append(did)

    return kept, DeduplicationReport(
        n_input_datasets=len(registry),
        n_output_datasets=len(kept),
        n_input_rules=0,
        n_output_rules=0,
        duplicate_dataset_pairs=duplicates,
        duplicate_rule_ids=[],
        removed_dataset_ids=removed_ids,
        removed_rule_ids=[],
        family_groups=family_groups,
    )


def deduplicate_rules(
    rules: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Remove duplicate rules by exact NL text match.

    Parameters
    ----------
    rules:
        List of dicts with keys: rule_id, nl_text, dataset_id.

    Returns
    -------
    (deduplicated_rules, list_of_removed_pairs)
    """
    seen_nl: dict[str, str] = {}  # nl_normalized → rule_id
    kept: list[dict[str, Any]] = []
    removed_pairs: list[tuple[str, str]] = []

    for rule in rules:
        nl = rule["nl_text"].lower().strip()
        if nl in seen_nl:
            removed_pairs.append((seen_nl[nl], rule["rule_id"]))
        else:
            seen_nl[nl] = rule["rule_id"]
            kept.append(rule)

    return kept, removed_pairs
