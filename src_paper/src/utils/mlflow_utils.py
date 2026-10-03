"""MLflow integration utilities.

Design rules (ADR-003):
- Every run gets a unique run_id.
- Metrics are logged ONLY after predictions are persisted to Parquet.
- Failed runs are logged with state=FAILED; never deleted silently.
- No metric is computed during inference; evaluators read Parquet files.
- Credentials (HF_TOKEN, etc.) are never logged as params.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

import mlflow

# Sensitive parameter names that must never be logged
_BLOCKED_PARAM_KEYS = frozenset({
    "hf_token", "huggingface_token", "kaggle_key", "kaggle_username",
    "api_key", "secret", "password", "token",
})


def _sanitize_params(params: dict[str, object]) -> dict[str, object]:
    """Remove any parameter whose key contains a sensitive keyword."""
    return {
        k: v for k, v in params.items()
        if not any(blocked in k.lower() for blocked in _BLOCKED_PARAM_KEYS)
    }


@contextmanager
def benchmark_run(
    run_name: str,
    params: dict[str, object] | None = None,
    tags: dict[str, str] | None = None,
    experiment_name: str = "nlq-quality-benchmark",
) -> Generator[mlflow.ActiveRun, None, None]:
    """Context manager for a single benchmark evaluation run.

    Automatically sets the experiment, sanitizes params (no secrets),
    and tags the run with ``state=FAILED`` on unhandled exceptions so
    runs are never silently dropped.

    Usage::

        with benchmark_run("B0_R-0001_seed42", params={...}) as active_run:
            run_id = active_run.info.run_id
            # ... do work ...
            mlflow.set_tag("state", "VALIDATED")

    Parameters
    ----------
    run_name:
        Human-readable name for the run.
    params:
        Run parameters (sanitized before logging).
    tags:
        Additional MLflow tags.
    experiment_name:
        MLflow experiment to log under.
    """
    mlflow.set_experiment(experiment_name)
    with mlflow.start_run(run_name=run_name) as active_run:
        try:
            # Log sanitized params
            if params:
                mlflow.log_params(_sanitize_params(params))
            if tags:
                mlflow.set_tags(tags)
            mlflow.set_tag("state", "IN_PROGRESS")
            yield active_run
        except Exception:
            mlflow.set_tag("state", "FAILED")
            raise


def log_metrics_from_predictions(
    run_id: str,
    metrics: dict[str, float],
) -> None:
    """Log aggregate metrics to an existing (completed) MLflow run.

    Must be called AFTER predictions are persisted to Parquet.
    This enforces the invariant: metrics are never computed during inference.

    Parameters
    ----------
    run_id:
        The MLflow run ID to update.
    metrics:
        Dict of metric name → float value.
    """
    with mlflow.start_run(run_id=run_id):
        mlflow.log_metrics(metrics)


def log_artifact(run_id: str, local_path: str) -> None:
    """Attach a local file as an artefact to an existing MLflow run."""
    with mlflow.start_run(run_id=run_id):
        mlflow.log_artifact(local_path)
