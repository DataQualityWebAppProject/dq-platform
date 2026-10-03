"""Dataset registry management — freeze, load, and audit pilot/full registries.

The registry is the source of truth for which datasets are included in each
experimental phase. Registries are version-controlled CSV files.

Design rules (R1, ADR-004):
- A frozen registry is immutable: new entries require a new version.
- The registry CSV contains no raw data — only identifiers and metadata.
- All modifications must go through freeze() to produce a new versioned file.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from models.dataset import DatasetRecord


_REGISTRY_DIR = Path("data/registry")
_REGISTRY_CSV = _REGISTRY_DIR / "datasets.csv"
_REGISTRY_FROZEN_DIR = _REGISTRY_DIR / "frozen"

_FIELDNAMES = [
    "owner", "slug", "url", "version", "license",
    "eligible", "eligibility_reason", "format",
    "n_tables", "sha256_files_json", "profile_path",
    "frozen_at", "phase",
]

PhaseT = Literal["pilot-20", "pilot-50", "full"]


def load_registry(registry_path: str | Path | None = None) -> list[DatasetRecord]:
    """Load the dataset registry from a CSV file.

    Parameters
    ----------
    registry_path:
        Path to the registry CSV. Defaults to ``data/registry/datasets.csv``.

    Returns
    -------
    List of DatasetRecord objects.
    """
    path = Path(registry_path) if registry_path else _REGISTRY_CSV
    if not path.exists():
        return []
    records: list[DatasetRecord] = []
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                sha256 = json.loads(row.get("sha256_files_json", "{}") or "{}")
                rec = DatasetRecord(
                    owner=row["owner"],
                    slug=row["slug"],
                    url=row["url"],  # type: ignore[arg-type]
                    version=row["version"],
                    license=row["license"],
                    eligible=row["eligible"].lower() == "true",
                    eligibility_reason=row.get("eligibility_reason", ""),
                    format=row.get("format", "unknown"),  # type: ignore[arg-type]
                    n_tables=int(row.get("n_tables", 1)),
                    sha256_files=sha256,
                    profile_path=row.get("profile_path") or None,
                )
                records.append(rec)
            except Exception:
                continue  # Skip malformed rows; don't raise
    return records


def freeze_registry(
    records: list[DatasetRecord],
    phase: PhaseT,
    registry_dir: str | Path | None = None,
) -> Path:
    """Freeze a set of dataset records to a versioned CSV file.

    The frozen registry file is named after the phase and current timestamp,
    making it append-only at the filesystem level.

    Parameters
    ----------
    records:
        List of DatasetRecord objects to freeze.
    phase:
        Experimental phase label.
    registry_dir:
        Directory for registry files. Defaults to ``data/registry/``.

    Returns
    -------
    Path to the newly written CSV file.
    """
    base = Path(registry_dir) if registry_dir else _REGISTRY_DIR
    frozen_dir = base / "frozen"
    frozen_dir.mkdir(parents=True, exist_ok=True)
    base.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = frozen_dir / f"{phase}_{ts}.csv"
    frozen_at = datetime.now(timezone.utc).isoformat()

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_FIELDNAMES)
        writer.writeheader()
        for rec in records:
            writer.writerow({
                "owner": rec.owner,
                "slug": rec.slug,
                "url": str(rec.url),
                "version": rec.version,
                "license": rec.license,
                "eligible": str(rec.eligible),
                "eligibility_reason": rec.eligibility_reason,
                "format": rec.format,
                "n_tables": rec.n_tables,
                "sha256_files_json": json.dumps(rec.sha256_files),
                "profile_path": rec.profile_path or "",
                "frozen_at": frozen_at,
                "phase": phase,
            })

    # Also update the canonical datasets.csv
    canonical = base / "datasets.csv"
    with canonical.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_FIELDNAMES)
        writer.writeheader()
        for rec in records:
            writer.writerow({
                "owner": rec.owner,
                "slug": rec.slug,
                "url": str(rec.url),
                "version": rec.version,
                "license": rec.license,
                "eligible": str(rec.eligible),
                "eligibility_reason": rec.eligibility_reason,
                "format": rec.format,
                "n_tables": rec.n_tables,
                "sha256_files_json": json.dumps(rec.sha256_files),
                "profile_path": rec.profile_path or "",
                "frozen_at": frozen_at,
                "phase": phase,
            })

    return out_path


def count_by_phase(registry_path: str | Path | None = None) -> dict[str, int]:
    """Count datasets per phase in the registry."""
    records = load_registry(registry_path)
    counts: dict[str, int] = {}
    # Read raw CSV for the phase column
    path = Path(registry_path) if registry_path else _REGISTRY_CSV
    if not path.exists():
        return counts
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            phase = row.get("phase", "unknown")
            counts[phase] = counts.get(phase, 0) + 1
    return counts
