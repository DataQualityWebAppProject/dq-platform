"""Intermediate Representation (IR) models.

The IR is the canonical, structured encoding of a natural-language quality rule
before code generation.  Every field that is ``None`` or an empty collection is
valid; the IR is built incrementally as agents resolve scope, evidence, etc.

Version history is handled by ``ir_version``; a migration helper must be added
here whenever the schema changes.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class IRScope(BaseModel):
    """Describes which tables/columns are in scope for the rule."""

    level: Literal["row", "group", "table", "cross_table"] = "row"
    tables: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class IRLogic(BaseModel):
    """Logical structure of the rule's condition."""

    operator: Literal["AND", "OR", "NOT", "IF", "IFF", "FORALL", "EXISTS", "NONE"] = "AND"
    clauses: list[dict] = Field(default_factory=list)  # type: ignore[type-arg]

    model_config = {"extra": "forbid"}


class IRAction(BaseModel):
    """What the rule does when the condition is (not) met."""

    mode: Literal["detect", "repair", "flag", "abstain"] = "detect"
    targets: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# Root IR model
# ---------------------------------------------------------------------------


_SUPPORTED_VERSIONS = frozenset({"1.0"})

_DimensionT = Literal[
    "completeness", "validity", "consistency", "uniqueness", "accuracy", "timeliness"
]
_ComplexityT = Literal["POINT_IN_TIME", "HISTORICAL", "ML_NECESSARY", "ABSTAIN"]


class IR(BaseModel):
    """Structured Intermediate Representation of a quality rule.

    Follows the minimal IR schema defined in the design document.
    All mutable default collections are wrapped in ``Field(default_factory=…)``
    to avoid shared-state bugs.
    """

    ir_version: str = "1.0"
    rule_id: str
    dimension: _DimensionT
    complexity: _ComplexityT
    scope: IRScope = Field(default_factory=IRScope)
    trigger: dict = Field(default_factory=dict)  # type: ignore[type-arg]
    logic: IRLogic = Field(default_factory=IRLogic)
    quantifier: str | None = None
    time_window: dict | None = None  # type: ignore[type-arg]
    evidence: list[dict] = Field(default_factory=list)  # type: ignore[type-arg]
    action: IRAction = Field(default_factory=IRAction)
    non_applicability: dict = Field(default_factory=dict)  # type: ignore[type-arg]
    ambiguities: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    model_config = {"extra": "ignore"}

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @field_validator("ir_version")
    @classmethod
    def _check_version(cls, v: str) -> str:
        if v not in _SUPPORTED_VERSIONS:
            raise ValueError(
                f"ir_version '{v}' is not supported. "
                f"Supported versions: {sorted(_SUPPORTED_VERSIONS)}"
            )
        return v

    @field_validator("rule_id")
    @classmethod
    def _check_rule_id(cls, v: str) -> str:
        import re

        # Accepts: R-0101 (POINT_IN_TIME) and R-H001 (HISTORICAL)
        if not re.match(r"^R-[H]?\d{3,4}$", v):
            raise ValueError(
                f"rule_id '{v}' does not match required pattern ^R-[H]?\\d{{3,4}}$"
            )
        return v
