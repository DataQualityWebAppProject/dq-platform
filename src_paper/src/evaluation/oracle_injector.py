"""Oracle Injector (T5.2) — Injects controlled errors into datasets to create ground truth.

Two-layer oracle strategy:
  1. Natural errors: already present in the original CSV (profiled, no oracle)
  2. Injected errors: deterministic violations with known row indices (oracle = injected indices)

F1 is computed against injected errors only.
Natural errors are reported separately as exploratory findings.

Reproducibility: every injection uses a fixed seed and records:
  - dataset_id, rule_id, injected_rows, injection_type, seed, hash of modified dataset
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np


@dataclass
class InjectionManifest:
    """Records exactly what was injected and where."""
    dataset_id: str
    rule_id: str
    injection_type: str           # validity, consistency, uniqueness, completeness, timeliness, accuracy
    target_columns: list[str]
    injected_row_indices: list[int]
    injection_details: list[dict]  # {row_idx, column, original_value, injected_value}
    seed: int
    n_injected: int
    original_hash: str
    modified_hash: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "dataset_id": self.dataset_id,
            "rule_id": self.rule_id,
            "injection_type": self.injection_type,
            "target_columns": self.target_columns,
            "injected_row_indices": self.injected_row_indices,
            "injection_details": self.injection_details,
            "seed": self.seed,
            "n_injected": self.n_injected,
            "original_hash": self.original_hash,
            "modified_hash": self.modified_hash,
            "created_at": self.created_at,
        }


@dataclass
class NaturalErrorReport:
    """Records natural errors found in the original dataset (no oracle)."""
    dataset_id: str
    column: str
    error_type: str
    n_errors: int
    sample_indices: list[int]
    description: str


def _hash_df(df: pd.DataFrame) -> str:
    return hashlib.sha256(
        pd.util.hash_pandas_object(df, index=True).values.tobytes()
    ).hexdigest()


def profile_natural_errors(df: pd.DataFrame, dataset_id: str) -> list[NaturalErrorReport]:
    """Detect natural errors in the dataset. No oracle — exploratory only."""
    reports = []
    for col in df.columns:
        # Nulls
        null_mask = df[col].isna()
        if null_mask.any():
            reports.append(NaturalErrorReport(
                dataset_id=dataset_id,
                column=col,
                error_type="null",
                n_errors=int(null_mask.sum()),
                sample_indices=null_mask[null_mask].index[:5].tolist(),
                description=f"{null_mask.sum()} null values in '{col}'",
            ))
        # Numeric outliers (> 3 sigma)
        if pd.api.types.is_numeric_dtype(df[col]):
            clean = df[col].dropna()
            if len(clean) > 10:
                mean, std = clean.mean(), clean.std()
                if std > 0:
                    outlier_mask = (df[col] - mean).abs() > 3 * std
                    if outlier_mask.any():
                        reports.append(NaturalErrorReport(
                            dataset_id=dataset_id,
                            column=col,
                            error_type="outlier_3sigma",
                            n_errors=int(outlier_mask.sum()),
                            sample_indices=df[outlier_mask].index[:5].tolist(),
                            description=f"{outlier_mask.sum()} outliers (>3σ) in '{col}'",
                        ))
        # Duplicates (whole-row)
    dup_mask = df.duplicated(keep=False)
    if dup_mask.any():
        reports.append(NaturalErrorReport(
            dataset_id=dataset_id,
            column="(all)",
            error_type="duplicate_row",
            n_errors=int(dup_mask.sum()),
            sample_indices=df[dup_mask].index[:5].tolist(),
            description=f"{dup_mask.sum()} duplicate rows",
        ))
    return reports


def inject_errors(
    df: pd.DataFrame,
    rule: dict,
    n_inject: int = 20,
    seed: int = 42,
    inject_fraction: float = 0.1,
) -> tuple[pd.DataFrame, InjectionManifest]:
    """Inject controlled errors into the DataFrame based on the rule's IR.

    Parameters
    ----------
    df:
        Clean DataFrame (natural errors should be removed or ignored beforehand).
    rule:
        Rule dict with ir_gold containing dimension, scope.columns, and logic.
    n_inject:
        Number of rows to inject errors into. Capped at inject_fraction * len(df).
    seed:
        Random seed for reproducibility.
    inject_fraction:
        Maximum fraction of rows to inject (default 10%).

    Returns
    -------
    (modified_df, manifest)
    """
    rng = random.Random(seed)
    np.random.seed(seed)

    rule_id = rule.get("rule_id", "unknown")
    dataset_id = rule.get("dataset_id", "unknown")
    ir = rule.get("ir_gold") or {}
    dimension = rule.get("dimension", "validity")
    target_cols = ir.get("scope", {}).get("columns", [])
    clauses = ir.get("logic", {}).get("clauses", [])

    # Filter to columns that actually exist in the DataFrame
    target_cols = [c for c in target_cols if c in df.columns]
    if not target_cols:
        # Fall back to first numeric/string columns
        target_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) or
                       pd.api.types.is_string_dtype(df[c])][:2]

    if not target_cols:
        target_cols = df.columns[:1].tolist()

    n_inject = min(n_inject, max(1, int(len(df) * inject_fraction)))
    all_indices = list(df.index)
    inject_indices = rng.sample(all_indices, min(n_inject, len(all_indices)))

    modified = df.copy()
    original_hash = _hash_df(df)
    details = []

    for idx in inject_indices:
        col = rng.choice(target_cols)
        original_val = modified.at[idx, col]
        col_dtype = str(modified[col].dtype)
        injected_val = _inject_by_dimension(dimension, clauses, col, original_val, rng, col_dtype)
        modified.at[idx, col] = injected_val
        details.append({
            "row_idx": int(idx),
            "column": col,
            "original_value": _serialize(original_val),
            "injected_value": _serialize(injected_val),
        })

    modified_hash = _hash_df(modified)
    manifest = InjectionManifest(
        dataset_id=dataset_id,
        rule_id=rule_id,
        injection_type=dimension,
        target_columns=target_cols,
        injected_row_indices=[int(i) for i in inject_indices],
        injection_details=details,
        seed=seed,
        n_injected=len(inject_indices),
        original_hash=original_hash,
        modified_hash=modified_hash,
    )
    return modified, manifest


def _is_date_column(series: Any, col_dtype: str) -> bool:
    """Detect if a column contains date/datetime values (string or int serial)."""
    import pandas as pd
    if "datetime" in col_dtype:
        return True
    # Check if string column looks like dates
    if "object" in col_dtype:
        sample = series.dropna().head(5)
        if len(sample) == 0:
            return False
        date_like = 0
        import re
        date_patterns = [
            r"^\d{4}-\d{2}-\d{2}",      # 2020-01-01
            r"^\d{1,2}/\d{1,2}/\d{4}",  # 1/5/2020
            r"^\d{2}-[A-Za-z]{3}-\d{2,4}", # 28-Feb-97
            r"^\d{1,2}/\d{1,2}/\d{2,4}", # 7/5/2011
        ]
        for val in sample:
            s = str(val)
            for pat in date_patterns:
                if re.match(pat, s):
                    date_like += 1
                    break
        return date_like >= len(sample) // 2
    return False


def _inject_by_dimension(
    dimension: str,
    clauses: list[dict],
    col: str,
    original_val: Any,
    rng: random.Random,
    col_dtype: str = "object",
) -> Any:
    """Return an injected value that violates the rule for the given dimension.

    Preserves the column dtype to avoid pandas dtype errors (BUG-008/009).
    For int64 columns, never returns a string value.
    """
    is_int = "int" in col_dtype
    is_float = "float" in col_dtype
    is_numeric = is_int or is_float

    if dimension == "completeness":
        return None  # inject null — works for all dtypes (NaN is universal)

    if dimension == "validity":
        for clause in clauses:
            if clause.get("field") == col:
                op = clause.get("op", "")
                val = clause.get("value")
                if op in ("gt", "gte") and isinstance(val, (int, float)):
                    result = val - abs(val) - 100
                    return int(result) if is_int else result
                if op in ("lt", "lte") and isinstance(val, (int, float)):
                    result = val + abs(val) + 100
                    return int(result) if is_int else result
                if op == "in" and isinstance(val, list):
                    if is_numeric:
                        # Can't inject a string into numeric column — inject out-of-range number
                        if isinstance(original_val, (int, float)) and not pd.isna(original_val):
                            return int(-abs(original_val) - 9999) if is_int else -abs(original_val) - 9999
                        return None
                    return "INJECTED_INVALID_ENUM_VALUE"
                if op == "matches_regex":
                    if is_numeric:
                        return int(-abs(original_val) - 9999) if is_int else -abs(original_val) - 9999
                    return "!!!INVALID_FORMAT_INJECTED!!!"
        # Default: inject negative if numeric, null if string
        if is_numeric and not pd.isna(original_val) if not isinstance(original_val, str) else False:
            result = -abs(original_val) - 9999
            return int(result) if is_int else result
        if isinstance(original_val, str):
            return None
        return None

    if dimension == "uniqueness":
        # BUG-008 FIX: preserve dtype — never inject string into int64
        if is_numeric:
            base = int(original_val) if is_int and not pd.isna(original_val) else original_val
            if base is None or (not isinstance(base, (int, float))):
                return None
            # Inject a far-out-of-range duplicate signal: add a large prime offset
            result = int(base) + 999983 if is_int else float(base) + 999983.0
            return result
        # String columns: duplicate by appending suffix
        return str(original_val) + "_DUP"

    if dimension == "consistency":
        # BUG-009 FIX: preserve dtype — never inject string into int64
        if is_numeric:
            if pd.isna(original_val) if not isinstance(original_val, str) else False:
                return None
            result = -int(original_val) - 1 if is_int else -float(original_val) - 1.0
            return result
        # BUG-014 FIX: detect date strings — inject out-of-range date preserving format
        if isinstance(original_val, str):
            import re
            # Map pattern → far-future date in same format
            date_format_map = [
                (r"^\d{4}-\d{2}-\d{2}", "2099-12-31"),          # 2020-01-01
                (r"^\d{1,2}/\d{1,2}/\d{4}", "12/31/2099"),      # 1/5/2020
                (r"^\d{2}-[A-Za-z]{3}-\d{2,4}", "31-Dec-99"),   # 28-Feb-97
                (r"^\d{1,2}/\d{1,2}/\d{2}", "12/31/99"),        # 7/5/11
            ]
            stripped = original_val.strip()
            for pattern, future_date in date_format_map:
                if re.match(pattern, stripped):
                    return future_date  # same format, far-future date
            # Not a date string — inject INCONS_ prefix
            return "INCONS_" + str(original_val)[:15]
        return None

    if dimension == "timeliness":
        if is_numeric:
            # Inject far-future timestamp as integer (epoch seconds year 2099)
            return int(4070908800) if is_int else 4070908800.0
        return "2099-12-31"

    if dimension == "accuracy":
        if is_numeric:
            if pd.isna(original_val) if not isinstance(original_val, str) else False:
                return None
            result = int(original_val) * -999 if is_int else float(original_val) * -999.0
            return result
        return "WRONG_VAL"

    # Default: inject null (safe for all dtypes)
    return None


def _serialize(val: Any) -> Any:
    if pd.isna(val) if not isinstance(val, str) else False:
        return None
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    return str(val) if not isinstance(val, (int, float, bool, type(None))) else val


def compute_f1(
    predicted_indices: list[int],
    oracle_indices: list[int],
    total_rows: int,
) -> dict[str, float]:
    """Compute precision, recall, F1 given predicted and oracle indices."""
    pred_set = set(predicted_indices)
    oracle_set = set(oracle_indices)
    tp = len(pred_set & oracle_set)
    fp = len(pred_set - oracle_set)
    fn = len(oracle_set - pred_set)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp, "fp": fp, "fn": fn,
        "n_predicted": len(pred_set),
        "n_oracle": len(oracle_set),
        "total_rows": total_rows,
    }
