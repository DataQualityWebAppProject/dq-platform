"""Kaggle API client wrapper for the NLQ Quality Benchmark.

Credentials are read ONLY from environment variables or ~/.kaggle/kaggle.json.
Supported credential formats:
  - KAGGLE_USERNAME + KAGGLE_KEY  (classic)
  - KAGGLE_API_TOKEN              (new format, starts with KGAT_)
  - ~/.kaggle/kaggle.json

Never commit credentials to the repository.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class CredentialsNotFoundError(RuntimeError):
    """Raised when Kaggle credentials are not found."""


@dataclass(frozen=True)
class DatasetMetadata:
    """Raw metadata record from the Kaggle API."""
    owner: str
    slug: str
    title: str
    url: str
    version: int
    license_name: str
    size_bytes: int
    total_votes: int
    usability_rating: float
    tags: list[str]
    file_types: list[str]
    description: str


def _check_credentials() -> None:
    """Raise CredentialsNotFoundError if Kaggle credentials are not available.

    Accepts:
      - KAGGLE_API_TOKEN env var (new format)
      - KAGGLE_USERNAME + KAGGLE_KEY env vars (classic format)
      - ~/.kaggle/kaggle.json file
    """
    # New format: single token
    if os.environ.get("KAGGLE_API_TOKEN"):
        return

    # Classic format: username + key
    if os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"):
        return

    # File-based credentials
    kaggle_json = Path.home() / ".kaggle" / "kaggle.json"
    if kaggle_json.exists():
        return

    raise CredentialsNotFoundError(
        "Kaggle credentials not found. Use one of:\n"
        "  1. Set KAGGLE_API_TOKEN environment variable (new format)\n"
        "  2. Set KAGGLE_USERNAME and KAGGLE_KEY environment variables\n"
        "  3. Place credentials at ~/.kaggle/kaggle.json\n"
        "Never commit credentials to the repository."
    )


class KaggleClient:
    """Thin wrapper around the official Kaggle Python API."""

    def __init__(self) -> None:
        _check_credentials()
        try:
            import kaggle  # type: ignore[import]
            self._api = kaggle.KaggleApi()
            self._api.authenticate()
        except ImportError as exc:
            raise ImportError(
                "The 'kaggle' package is required. Install: pip install kaggle"
            ) from exc

    def search_datasets(
        self,
        search: str = "",
        file_type: str = "csv",
        license_name: str = "cc",
        page: int = 1,
    ) -> list[DatasetMetadata]:
        results = self._api.dataset_list(
            search=search,
            file_type=file_type,
            license_name=license_name,
            page=page,
        )
        return [self._to_metadata(r) for r in (results or [])]

    def get_dataset_metadata(self, owner: str, slug: str) -> DatasetMetadata:
        info = self._api.dataset_view(f"{owner}/{slug}")
        return self._to_metadata(info)

    def list_dataset_files(self, owner: str, slug: str) -> list[dict[str, Any]]:
        files = self._api.dataset_list_files(f"{owner}/{slug}")
        result: list[dict[str, Any]] = []
        for f in files.files if hasattr(files, "files") else []:
            result.append({
                "name": getattr(f, "name", str(f)),
                "size": getattr(f, "size", 0),
            })
        return result

    def _to_metadata(self, raw: Any) -> DatasetMetadata:
        owner_ref = getattr(raw, "ownerRef", "") or getattr(raw, "owner_ref", "")
        if "/" in str(owner_ref):
            owner, slug = str(owner_ref).split("/", 1)
        else:
            owner = str(owner_ref)
            slug = getattr(raw, "slug", getattr(raw, "ref", "")).split("/")[-1]
        license_obj = getattr(raw, "licenseName", None) or getattr(raw, "license_name", "unknown")
        tags_raw = getattr(raw, "tags", []) or []
        file_types_raw = getattr(raw, "fileTypes", []) or getattr(raw, "file_types", [])
        return DatasetMetadata(
            owner=owner, slug=slug,
            title=str(getattr(raw, "title", "")),
            url=f"https://www.kaggle.com/datasets/{owner}/{slug}",
            version=int(getattr(raw, "currentDatasetVersionNumber", 1) or 1),
            license_name=str(license_obj),
            size_bytes=int(getattr(raw, "totalBytes", 0) or 0),
            total_votes=int(getattr(raw, "voteCount", 0) or 0),
            usability_rating=float(getattr(raw, "usabilityRating", 0.0) or 0.0),
            tags=[str(t) for t in tags_raw],
            file_types=[str(t) for t in file_types_raw],
            description=str(getattr(raw, "description", ""))[:500],
        )
