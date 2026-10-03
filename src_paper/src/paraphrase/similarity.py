"""Similarity measures and drift/clustering detection for paraphrases.

Per Wang & Zhu (2024/2026): paraphrase diversity is critical.
- Too-similar paraphrases → false negatives (same error, looks like agreement)
- Too-dissimilar paraphrases → false positives (semantic drift)

This module computes token-level Jaccard similarity and detects
clustering (paraphrases that are too similar to each other).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class SimilarityResult:
    """Pairwise similarity between two texts."""
    text_a: str
    text_b: str
    jaccard: float
    is_too_similar: bool   # above upper threshold
    is_too_dissimilar: bool  # below lower threshold


@dataclass
class DriftReport:
    """Report on clustering/drift in a set of paraphrases."""
    n_paraphrases: int
    pairwise_similarities: list[SimilarityResult]
    n_too_similar: int
    n_too_dissimilar: int
    recommendation: str


def _tokenize(text: str) -> set[str]:
    """Tokenize text into lowercase word set."""
    return set(re.findall(r"\b\w+\b", text.lower()))


def jaccard_similarity(text_a: str, text_b: str) -> float:
    """Compute Jaccard similarity between two texts."""
    toks_a = _tokenize(text_a)
    toks_b = _tokenize(text_b)
    if not toks_a and not toks_b:
        return 1.0
    union = toks_a | toks_b
    intersection = toks_a & toks_b
    return len(intersection) / len(union)


def check_drift(
    paraphrases: list[str],
    min_similarity: float = 0.3,
    max_similarity: float = 0.95,
) -> DriftReport:
    """Check paraphrase set for clustering or semantic drift.

    Parameters
    ----------
    paraphrases:
        List of paraphrase strings.
    min_similarity:
        Below this → likely semantic drift (too dissimilar).
    max_similarity:
        Above this → likely clustered (too similar, near-duplicates).

    Returns
    -------
    DriftReport with pairwise similarities and recommendations.
    """
    pairwise: list[SimilarityResult] = []
    n = len(paraphrases)

    for i in range(n):
        for j in range(i + 1, n):
            sim = jaccard_similarity(paraphrases[i], paraphrases[j])
            pairwise.append(SimilarityResult(
                text_a=paraphrases[i][:80],
                text_b=paraphrases[j][:80],
                jaccard=sim,
                is_too_similar=sim > max_similarity,
                is_too_dissimilar=sim < min_similarity,
            ))

    n_too_similar = sum(1 for r in pairwise if r.is_too_similar)
    n_too_dissimilar = sum(1 for r in pairwise if r.is_too_dissimilar)

    if n_too_similar > 0:
        rec = (
            f"{n_too_similar} paraphrase pair(s) are too similar (Jaccard > {max_similarity}). "
            "Re-generate with higher diversity."
        )
    elif n_too_dissimilar > 0:
        rec = (
            f"{n_too_dissimilar} paraphrase pair(s) may have drifted semantically "
            f"(Jaccard < {min_similarity}). Verify equivalence manually."
        )
    else:
        rec = "Diversity is within acceptable range."

    return DriftReport(
        n_paraphrases=n,
        pairwise_similarities=pairwise,
        n_too_similar=n_too_similar,
        n_too_dissimilar=n_too_dissimilar,
        recommendation=rec,
    )
