"""RuleRecord — canonical quality rule with lifecycle metadata.

A rule starts as a ``DRAFT`` (machine-generated or human-authored skeleton),
progresses to ``REVIEWED`` once a human approves text, IR, oracle and test
cases, and is finally ``FROZEN`` when it enters the benchmark.

Only ``FROZEN`` rules participate in the test split.  The IR gold label
(``ir_gold``) is stored separately from the predicted IR so that evaluators
never receive the gold during generation.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .ir import IR


_RULE_ID_RE = re.compile(r"^R-\d{4}$")

_DimensionT = Literal[
    "completeness", "validity", "consistency", "uniqueness", "accuracy", "timeliness"
]
_ComplexityT = Literal["POINT_IN_TIME", "HISTORICAL", "ML_NECESSARY", "ABSTAIN"]
_StatusT = Literal["DRAFT", "REVIEWED", "FROZEN"]


class RuleRecord(BaseModel):
    """A single canonical quality rule in the benchmark corpus.

    Fields
    ------
    rule_id
        Unique identifier matching ``^R-\\d{4}$``.
    dataset_id
        Parent dataset in the form ``owner/slug``.
    nl_text
        Natural-language formulation of the rule (≥ 10 characters).
    dimension
        Quality dimension the rule targets.
    complexity
        Routing complexity assigned by the classifier.
    status
        Lifecycle state.  Only ``FROZEN`` rules enter the test split.
    ir_gold
        Human-approved gold IR; ``None`` until review.
    oracle
        Expected output for at least one concrete example (``None`` until review).
    paraphrases
        Alternative natural-language formulations (same semantics).
    test_cases
        List of ``{"input": …, "expected": …}`` dicts.
    created_at
        UTC timestamp of record creation.
    reviewed_by
        Username of the human reviewer; required for ``REVIEWED`` / ``FROZEN``.
    reviewed_at
        UTC timestamp of review; required for ``REVIEWED`` / ``FROZEN``.
    """

    rule_id: str = Field(pattern=r"^R-\d{4}$")
    dataset_id: str
    nl_text: str = Field(min_length=10)
    dimension: _DimensionT
    complexity: _ComplexityT
    status: _StatusT
    ir_gold: IR | None = None
    oracle: dict | None = None  # type: ignore[type-arg]
    paraphrases: list[str] = Field(default_factory=list)
    test_cases: list[dict] = Field(default_factory=list)  # type: ignore[type-arg]
    created_at: datetime
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None

    model_config = {"extra": "forbid"}

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @field_validator("rule_id")
    @classmethod
    def _rule_id_pattern(cls, v: str) -> str:
        if not _RULE_ID_RE.match(v):
            raise ValueError(
                f"rule_id '{v}' must match ^R-\\d{{4}}$ (e.g. R-0001)"
            )
        return v

    @model_validator(mode="after")
    def _review_fields_required(self) -> RuleRecord:
        """``reviewed_by`` and ``reviewed_at`` are mandatory for reviewed/frozen rules."""
        if self.status in ("REVIEWED", "FROZEN"):
            if not self.reviewed_by:
                raise ValueError(
                    f"reviewed_by must be set when status='{self.status}'"
                )
            if self.reviewed_at is None:
                raise ValueError(
                    f"reviewed_at must be set when status='{self.status}'"
                )
        return self
