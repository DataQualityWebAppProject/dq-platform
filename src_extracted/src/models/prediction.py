"""Prediction — row-level evaluation output.

Each ``Prediction`` records what the system decided for a single row (or entity)
in a dataset, against a specific rule and run.  Predictions are the atomic unit
of evaluation: all aggregate metrics are computed by reading persisted
``Prediction`` rows and must never be hard-coded or derived from in-memory state.

Predictions are written once and never updated.  A repair attempt produces a new
``Prediction`` with ``attempt`` incremented; the original is retained.

The ``gold_label`` may be ``None`` for rows where ground truth is unavailable
(e.g. unlabelled held-out rows during generation).  These rows are excluded from
metric calculations automatically.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Prediction(BaseModel):
    """Row-level prediction produced by the evaluation pipeline.

    Fields
    ------
    run_id
        Foreign key to the parent ``RunManifest``.
    rule_id
        Rule being evaluated.
    dataset_id
        Parent dataset in the form ``owner/slug``.
    row_id
        Zero-based integer index of the row within the dataset.
    predicted_label
        System's binary quality judgement for this row.
    gold_label
        Ground-truth label; ``None`` when not available.
    repair_value
        Value proposed by a repair agent, if applicable.
    gold_repair
        Ground-truth repaired value, if available.
    attempt
        Repair attempt counter; 1 for the initial prediction.
    state
        Final state-machine state at the time this prediction was written.
    elapsed_ms
        Wall-clock time for this individual prediction in milliseconds.
    timestamp_utc
        UTC timestamp when this prediction was persisted.
    """

    run_id: str
    rule_id: str
    dataset_id: str
    row_id: int = Field(ge=0)
    predicted_label: bool
    gold_label: bool | None = None
    repair_value: Any | None = None
    gold_repair: Any | None = None
    attempt: int = Field(default=1, ge=1)
    state: str
    elapsed_ms: float = Field(ge=0.0)
    timestamp_utc: datetime

    model_config = {"extra": "forbid"}
