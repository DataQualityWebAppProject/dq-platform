"""Eligibility and license pipeline for Kaggle dataset candidates.

Rules (R1, R2):
- Dataset must have a permissive license (CC0, CC-BY, or similar).
- Format must be tabular: CSV, TSV, JSON, Parquet, or multi-table.
- Size must be > 0 and <= MAX_SIZE_MB.
- Must have at least one file.
- Owner/slug must be unique in the registry.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from data_registry.kaggle_client import DatasetMetadata


MAX_SIZE_MB: int = 500

# License keywords considered permissive
_PERMISSIVE_LICENSE_KEYWORDS: frozenset[str] = frozenset({
    "cc0", "cc-by", "cc by", "public domain", "open data", "mit", "apache",
    "odc-by", "odc by", "dbcl", "open database",
})

# File types that indicate tabular data
_TABULAR_FILE_TYPES: frozenset[str] = frozenset({
    "csv", "tsv", "json", "parquet", "xlsx", "xls",
})


@dataclass(frozen=True)
class EligibilityResult:
    """Result of the eligibility check for one dataset."""
    eligible: bool
    reason: str
    detected_format: Literal["csv", "tsv", "json", "parquet", "multitable", "unknown"]


def check_eligibility(meta: DatasetMetadata) -> EligibilityResult:
    """Check whether a dataset is eligible for the benchmark.

    Parameters
    ----------
    meta:
        Metadata from the Kaggle API.

    Returns
    -------
    EligibilityResult with eligible=True only if all criteria pass.
    """
    # License check
    license_lower = meta.license_name.lower()
    has_permissive = any(kw in license_lower for kw in _PERMISSIVE_LICENSE_KEYWORDS)
    if not has_permissive:
        return EligibilityResult(
            eligible=False,
            reason=f"Non-permissive license: '{meta.license_name}'",
            detected_format="unknown",
        )

    # Size check
    size_mb = meta.size_bytes / (1024 * 1024)
    if meta.size_bytes == 0:
        return EligibilityResult(
            eligible=False,
            reason="Dataset reports 0 bytes — likely empty or unavailable.",
            detected_format="unknown",
        )
    if size_mb > MAX_SIZE_MB:
        return EligibilityResult(
            eligible=False,
            reason=f"Dataset too large: {size_mb:.1f} MB > {MAX_SIZE_MB} MB limit.",
            detected_format="unknown",
        )

    # Format check
    file_types_lower = {ft.lower() for ft in meta.file_types}
    detected: Literal["csv", "tsv", "json", "parquet", "multitable", "unknown"] = "unknown"

    tabular_types = file_types_lower & _TABULAR_FILE_TYPES
    if not tabular_types:
        return EligibilityResult(
            eligible=False,
            reason=f"No tabular file types detected. Found: {sorted(file_types_lower) or ['none']}",
            detected_format="unknown",
        )

    # Determine format
    if len(tabular_types) > 1 or "csv" in tabular_types and len(meta.file_types) > 1:
        detected = "multitable"
    elif "csv" in tabular_types:
        detected = "csv"
    elif "tsv" in tabular_types:
        detected = "tsv"
    elif "json" in tabular_types:
        detected = "json"
    elif "parquet" in tabular_types:
        detected = "parquet"

    return EligibilityResult(eligible=True, reason="Passed all eligibility checks.", detected_format=detected)


def build_candidate_pool(
    metadata_list: list[DatasetMetadata],
    existing_ids: set[str] | None = None,
) -> tuple[list[tuple[DatasetMetadata, EligibilityResult]], list[tuple[DatasetMetadata, EligibilityResult]]]:
    """Partition a list of metadata records into eligible and ineligible.

    Parameters
    ----------
    metadata_list:
        List of metadata records from Kaggle search.
    existing_ids:
        Set of already-registered dataset IDs (owner/slug) to skip as duplicates.

    Returns
    -------
    Tuple of (eligible, ineligible) — each a list of (metadata, result) pairs.
    """
    if existing_ids is None:
        existing_ids = set()

    eligible: list[tuple[DatasetMetadata, EligibilityResult]] = []
    ineligible: list[tuple[DatasetMetadata, EligibilityResult]] = []

    for meta in metadata_list:
        dataset_id = f"{meta.owner}/{meta.slug}"
        if dataset_id in existing_ids:
            ineligible.append((meta, EligibilityResult(
                eligible=False,
                reason=f"Duplicate: '{dataset_id}' already in registry.",
                detected_format="unknown",
            )))
            continue
        result = check_eligibility(meta)
        if result.eligible:
            eligible.append((meta, result))
        else:
            ineligible.append((meta, result))

    return eligible, ineligible
