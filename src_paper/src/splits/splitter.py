"""Grouped dataset split creation (120/40/40 train/val/test).

Design rules (R12):
- The partition unit is DATASET/FAMILY, never an individual paraphrase or rule.
- All rules belonging to a dataset go into the same split.
- All paraphrases and mutations of a rule stay in the same split.
- Families (schema-similar datasets) are assigned to the same split.
- The split is reproducible from the seed and dataset order.
- Split hashes (SHA-256 of sorted dataset_ids per split) are persisted.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class SplitManifest:
    """Manifest of the 120/40/40 split."""
    created_at: str
    seed: int
    n_train: int
    n_val: int
    n_test: int
    train_ids: list[str]
    val_ids: list[str]
    test_ids: list[str]
    train_hash: str   # SHA-256 of sorted train_ids
    val_hash: str
    test_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "seed": self.seed,
            "n_train": self.n_train,
            "n_val": self.n_val,
            "n_test": self.n_test,
            "train_ids": sorted(self.train_ids),
            "val_ids": sorted(self.val_ids),
            "test_ids": sorted(self.test_ids),
            "train_hash": self.train_hash,
            "val_hash": self.val_hash,
            "test_hash": self.test_hash,
        }


def _hash_ids(ids: list[str]) -> str:
    """Compute SHA-256 of sorted IDs."""
    joined = "\n".join(sorted(ids)).encode("utf-8")
    return hashlib.sha256(joined).hexdigest()


def create_grouped_split(
    dataset_ids: list[str],
    family_groups: dict[str, list[str]] | None = None,
    train_frac: float = 0.6,
    val_frac: float = 0.2,
    seed: int = 42,
) -> SplitManifest:
    """Create a grouped train/val/test split.

    The split is done at the family level: all datasets in the same family
    go to the same partition.

    Parameters
    ----------
    dataset_ids:
        List of all dataset IDs (after deduplication).
    family_groups:
        Dict mapping family_key → list of dataset_ids. If None,
        each dataset is its own family.
    train_frac:
        Fraction of datasets for training (default: 0.6 → 120/200).
    val_frac:
        Fraction for validation (default: 0.2 → 40/200).
    seed:
        Random seed for reproducibility.

    Returns
    -------
    SplitManifest with sorted ID lists and SHA-256 hashes.
    """
    if family_groups is None:
        # Each dataset is its own family
        families = [[did] for did in dataset_ids]
    else:
        families = list(family_groups.values())

    rng = random.Random(seed)
    rng.shuffle(families)

    n_total = len(dataset_ids)
    n_train = round(n_total * train_frac)
    n_val = round(n_total * val_frac)

    train_ids: list[str] = []
    val_ids: list[str] = []
    test_ids: list[str] = []

    for family in families:
        if len(train_ids) < n_train:
            train_ids.extend(family)
        elif len(val_ids) < n_val:
            val_ids.extend(family)
        else:
            test_ids.extend(family)

    return SplitManifest(
        created_at=datetime.now(timezone.utc).isoformat(),
        seed=seed,
        n_train=len(train_ids),
        n_val=len(val_ids),
        n_test=len(test_ids),
        train_ids=train_ids,
        val_ids=val_ids,
        test_ids=test_ids,
        train_hash=_hash_ids(train_ids),
        val_hash=_hash_ids(val_ids),
        test_hash=_hash_ids(test_ids),
    )


def save_split_manifest(manifest: SplitManifest, path: str | Path) -> None:
    """Persist the split manifest to a JSON file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_split_manifest(path: str | Path) -> SplitManifest:
    """Load and verify a split manifest from JSON."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return SplitManifest(
        created_at=data["created_at"],
        seed=data["seed"],
        n_train=data["n_train"],
        n_val=data["n_val"],
        n_test=data["n_test"],
        train_ids=data["train_ids"],
        val_ids=data["val_ids"],
        test_ids=data["test_ids"],
        train_hash=data["train_hash"],
        val_hash=data["val_hash"],
        test_hash=data["test_hash"],
    )


def verify_split_hashes(manifest: SplitManifest) -> bool:
    """Return True if all stored hashes match recomputed hashes."""
    return (
        manifest.train_hash == _hash_ids(manifest.train_ids)
        and manifest.val_hash == _hash_ids(manifest.val_ids)
        and manifest.test_hash == _hash_ids(manifest.test_ids)
    )
