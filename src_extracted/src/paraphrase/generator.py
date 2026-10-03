"""Paraphrase generator for metamorphic testing (Wang & Zhu 2024/2026).

Design rules:
- Only the NL description text is paraphrased.
- Schema info (column names, types), function signatures, and examples are FROZEN.
- The paraphrase generator may use an LLM, but the frozen parts must be injected
  back after generation to prevent schema drift.
- Paraphrases are semantically equivalent — same rule, different wording.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ParaphraseRequest:
    """Input to the paraphrase generator."""
    rule_id: str
    nl_text: str
    frozen_schema: list[str]   # Column names that must not be altered
    frozen_examples: list[str] # Example strings that must not be altered
    n_paraphrases: int = 5     # Number of paraphrase variants to generate


@dataclass
class ParaphraseResult:
    """Output from the paraphrase generator."""
    rule_id: str
    paraphrases: list[str]
    frozen_schema: list[str]
    frozen_examples: list[str]
    warnings: list[str]


def generate_paraphrases(
    request: ParaphraseRequest,
    llm_fn: Callable[[str, int], list[str]] | None = None,
) -> ParaphraseResult:
    """Generate paraphrases of the NL rule text.

    Parameters
    ----------
    request:
        ParaphraseRequest with the rule text and frozen elements.
    llm_fn:
        Optional LLM function: (nl_text, n) → list of n paraphrases.
        If None, returns simple word-order variations (testing only).

    Returns
    -------
    ParaphraseResult with n paraphrases and any schema-drift warnings.
    """
    if llm_fn is not None:
        raw_paraphrases = llm_fn(request.nl_text, request.n_paraphrases)
    else:
        # Fallback: return the original text repeated (testing only, not real paraphrase)
        raw_paraphrases = [request.nl_text] * request.n_paraphrases

    # Post-process: verify frozen schema elements are preserved
    cleaned = []
    warnings = []
    for i, p in enumerate(raw_paraphrases):
        p_clean = p
        schema_ok = True
        for col in request.frozen_schema:
            if col not in p_clean:
                # Re-inject the column name if missing
                warnings.append(
                    f"Paraphrase {i}: column '{col}' was dropped — re-injected."
                )
                # Simple heuristic: append a note about the column
                p_clean = p_clean.rstrip(".") + f" (column: {col})."
                schema_ok = False

        for ex in request.frozen_examples:
            if ex not in p_clean:
                warnings.append(
                    f"Paraphrase {i}: example '{ex[:30]}' was dropped — re-injected."
                )
                p_clean = p_clean + f" Example: {ex}"

        cleaned.append(p_clean)

    return ParaphraseResult(
        rule_id=request.rule_id,
        paraphrases=cleaned,
        frozen_schema=request.frozen_schema,
        frozen_examples=request.frozen_examples,
        warnings=warnings,
    )


def check_schema_preserved(paraphrase: str, schema_columns: list[str]) -> bool:
    """Check that all schema column names appear in the paraphrase."""
    return all(col in paraphrase for col in schema_columns)
