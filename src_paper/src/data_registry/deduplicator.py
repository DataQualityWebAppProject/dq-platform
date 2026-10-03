"""Mirror and duplicate detection for the dataset registry.

Detection methods:
1. Exact slug match (owner/slug).
2. File hash match (all SHA-256s identical → same content, different name).
3. Schema similarity (same column names → likely mirror or fork).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DuplicateResult:
    """Result of a duplicate check between two datasets."""
    dataset_id_a: str
    dataset_id_b: str
    duplicate_type: str  # "exact_slug", "hash_match", "schema_similar"
    similarity_score: float  # 0.0–1.0; 1.0 = identical
    notes: str = ""


def _jaccard(set_a: set[str], set_b: set[str]) -> float:
    """Compute Jaccard similarity between two sets of strings."""
    if not set_a and not set_b:
        return 1.0
    union = set_a | set_b
    intersection = set_a & set_b
    return len(intersection) / len(union)


def detect_duplicates(
    registry: list[dict[str, Any]],
    schema_similarity_threshold: float = 0.8,
) -> list[DuplicateResult]:
    """Scan a list of dataset registry entries for duplicates.

    Each entry must have keys:
    - ``dataset_id``: str (owner/slug)
    - ``sha256_files``: dict[str, str] (filename → sha256 hex)
    - ``column_names``: list[str] (optional; from profile)

    Parameters
    ----------
    registry:
        List of dataset metadata dicts.
    schema_similarity_threshold:
        Jaccard similarity above which two datasets are flagged as mirrors.

    Returns
    -------
    List of DuplicateResult records (may be empty).
    """
    results: list[DuplicateResult] = []
    n = len(registry)

    # Build lookup structures
    slug_seen: dict[str, int] = {}  # dataset_id → first index

    for i in range(n):
        entry = registry[i]
        dataset_id = entry["dataset_id"]

        # 1. Exact slug duplicate
        if dataset_id in slug_seen:
            j = slug_seen[dataset_id]
            results.append(DuplicateResult(
                dataset_id_a=registry[j]["dataset_id"],
                dataset_id_b=dataset_id,
                duplicate_type="exact_slug",
                similarity_score=1.0,
                notes="Identical owner/slug.",
            ))
        else:
            slug_seen[dataset_id] = i

    # 2. Hash match and schema similarity (O(n²) — acceptable for ≤ 300 datasets)
    for i in range(n):
        for j in range(i + 1, n):
            a = registry[i]
            b = registry[j]
            id_a = a["dataset_id"]
            id_b = b["dataset_id"]

            # Hash match: all file hashes in a are present in b
            hashes_a = set(a.get("sha256_files", {}).values())
            hashes_b = set(b.get("sha256_files", {}).values())
            if hashes_a and hashes_b and hashes_a == hashes_b:
                results.append(DuplicateResult(
                    dataset_id_a=id_a,
                    dataset_id_b=id_b,
                    duplicate_type="hash_match",
                    similarity_score=1.0,
                    notes="Identical file hashes — same content under different slug.",
                ))
                continue

            # Schema similarity
            cols_a = set(a.get("column_names", []))
            cols_b = set(b.get("column_names", []))
            if cols_a or cols_b:
                sim = _jaccard(cols_a, cols_b)
                if sim >= schema_similarity_threshold:
                    results.append(DuplicateResult(
                        dataset_id_a=id_a,
                        dataset_id_b=id_b,
                        duplicate_type="schema_similar",
                        similarity_score=sim,
                        notes=f"Column Jaccard similarity={sim:.2f} ≥ {schema_similarity_threshold}.",
                    ))

    return results
