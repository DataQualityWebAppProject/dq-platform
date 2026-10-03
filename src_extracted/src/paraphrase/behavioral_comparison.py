"""Behavioral comparison for metamorphic paraphrase validation.

Per Wang & Zhu (2024/2026): paraphrases must produce the same output
on the same inputs. If they disagree, one of them is wrong — or the
rule is genuinely ambiguous.

Voting strategies:
- majority: more than half must agree
- conservative: any disagreement triggers a failure (maximum recall)
- unanimous: all must agree (maximum precision)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal


VotingStrategyT = Literal["majority", "conservative", "unanimous"]


@dataclass
class BehavioralResult:
    """Result of behavioral comparison for one input."""
    input_data: dict[str, Any]
    outputs: list[bool | None]    # One per paraphrase
    verdict: bool | None          # None = ABSTAIN (disagreement)
    strategy: VotingStrategyT
    agreement: float              # Fraction of paraphrases that match verdict
    is_discordant: bool           # True if paraphrases disagree


@dataclass
class MetamorphicReport:
    """Full report for a set of paraphrases over a set of inputs."""
    rule_id: str
    n_paraphrases: int
    n_inputs: int
    strategy: VotingStrategyT
    results: list[BehavioralResult] = field(default_factory=list)
    n_discordant: int = 0
    recall_estimate: float = 0.0
    notes: str = ""


def compare_behaviors(
    rule_id: str,
    evaluate_fns: list[Callable[[dict[str, Any]], bool | None]],
    test_inputs: list[dict[str, Any]],
    strategy: VotingStrategyT = "majority",
) -> MetamorphicReport:
    """Run behavioral comparison across paraphrase evaluation functions.

    Parameters
    ----------
    rule_id:
        The rule being validated.
    evaluate_fns:
        List of evaluation functions, one per paraphrase.
        Each function takes an input dict and returns bool or None.
    test_inputs:
        List of input dicts to evaluate each function on.
    strategy:
        Voting strategy for aggregating outputs.

    Returns
    -------
    MetamorphicReport with per-input verdicts and aggregate stats.
    """
    results: list[BehavioralResult] = []

    for inp in test_inputs:
        outputs = []
        for fn in evaluate_fns:
            try:
                outputs.append(fn(inp))
            except Exception:
                outputs.append(None)

        verdict, agreement = _apply_strategy(outputs, strategy)
        is_discordant = not _all_agree(outputs)

        results.append(BehavioralResult(
            input_data=inp,
            outputs=outputs,
            verdict=verdict,
            strategy=strategy,
            agreement=agreement,
            is_discordant=is_discordant,
        ))

    n_discordant = sum(1 for r in results if r.is_discordant)
    n_positive = sum(1 for r in results if r.verdict is True)
    recall_estimate = n_positive / max(len(results), 1)

    return MetamorphicReport(
        rule_id=rule_id,
        n_paraphrases=len(evaluate_fns),
        n_inputs=len(test_inputs),
        strategy=strategy,
        results=results,
        n_discordant=n_discordant,
        recall_estimate=recall_estimate,
        notes=f"Strategy: {strategy}; discordant inputs: {n_discordant}/{len(results)}",
    )


def _apply_strategy(
    outputs: list[bool | None],
    strategy: VotingStrategyT,
) -> tuple[bool | None, float]:
    """Apply voting strategy to aggregate outputs into a verdict."""
    valid = [o for o in outputs if o is not None]
    n = len(outputs)
    if n == 0:
        return None, 0.0

    n_true = sum(1 for o in valid if o is True)
    n_false = sum(1 for o in valid if o is False)
    n_valid = len(valid)

    if strategy == "majority":
        if n_valid == 0:
            return None, 0.0
        verdict = n_true > n_valid / 2
        agreement = max(n_true, n_false) / n
        return verdict, agreement

    elif strategy == "conservative":
        # Any disagreement → None (ABSTAIN)
        if _all_agree(outputs):
            verdict = valid[0] if valid else None
            return verdict, 1.0
        return None, max(n_true, n_false) / n

    else:  # unanimous
        if n_valid == n and _all_agree(outputs):
            return valid[0], 1.0
        return None, max(n_true, n_false) / n


def _all_agree(outputs: list[bool | None]) -> bool:
    """Return True if all non-None outputs are the same."""
    valid = [o for o in outputs if o is not None]
    return len(set(valid)) <= 1
