"""DatasetRecord — registry entry for a single Kaggle dataset.

Each entry represents one dataset that has been (or is being) evaluated for
eligibility.  Once a dataset is eligible and downloaded its artifacts are
tracked here so that any re-run can verify provenance without re-downloading.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import AnyUrl, BaseModel, Field, field_validator, model_validator


_SLUG_RE = re.compile(r"^[a-z0-9_-]+$")

_FormatT = Literal["csv", "tsv", "json", "parquet", "multitable", "unknown"]


class DatasetRecord(BaseModel):
    """Immutable registry record for a single Kaggle dataset.

    Fields
    ------
    owner
        Kaggle username or organisation that owns the dataset.
    slug
        URL-safe dataset identifier (lower-case letters, digits, ``_`` and ``-``).
    url
        Canonical Kaggle URL for reproducibility.
    version
        Dataset version string as reported by the Kaggle API.
    license
        SPDX identifier or human-readable licence name.
    downloaded_at
        UTC timestamp of last successful download; ``None`` if not yet downloaded.
    sha256_files
        Mapping ``{filename: sha256_hex}`` for every file in the dataset archive.
    eligible
        Whether the dataset passed all eligibility checks.
    eligibility_reason
        Free-text explanation of the eligibility decision (required when
        ``eligible`` is ``False``; optional but encouraged otherwise).
    format
        Primary file format detected in the archive.
    n_tables
        Number of tables (CSV/Parquet files) found in the archive; defaults to 1.
    profile_path
        Relative path to the DuckDB/Parquet profile artefact, if available.
    """

    owner: str
    slug: str
    url: AnyUrl
    version: str
    license: str  # noqa: A003 – shadows built-in but matches domain language
    downloaded_at: datetime | None = None
    sha256_files: dict[str, str] = Field(default_factory=dict)
    eligible: bool
    eligibility_reason: str = ""
    format: _FormatT = "unknown"  # noqa: A003
    n_tables: int = Field(default=1, ge=1)
    profile_path: str | None = None

    model_config = {"extra": "forbid"}

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @field_validator("slug")
    @classmethod
    def _slug_pattern(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError(
                f"slug '{v}' must match ^[a-z0-9_-]+$ "
                "(lower-case letters, digits, underscores and hyphens only)"
            )
        return v

    @model_validator(mode="after")
    def _ineligible_requires_reason(self) -> DatasetRecord:
        if not self.eligible and not self.eligibility_reason:
            raise ValueError(
                "eligibility_reason must be set when eligible=False"
            )
        return self

    # ------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------

    @property
    def dataset_id(self) -> str:
        """Canonical identifier in the form ``owner/slug``."""
        return f"{self.owner}/{self.slug}"
