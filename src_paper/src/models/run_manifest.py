"""RunManifest — per-run provenance and metrics record.

Every evaluation run (one rule × one variant × one model × one phase) is
tracked in a ``RunManifest``.  Manifests are append-only: a re-run produces a
new manifest with ``attempt`` incremented; the old manifest is never overwritten.

The ``run_id`` is a UUID string generated at run creation time.  It serves as
the foreign key linking manifests to ``Prediction`` rows and MLflow runs.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# Variant codes
# B0 = direct prompt, B1 = structured prompt, B2 = RAG/few-shot,
# B3 = QLoRA NL→code, B4 = QLoRA NL→IR, B5 = full system w/ QLoRA,
# P  = full system w/o QLoRA
_VariantT = Literal["B0", "B1", "B2", "B3", "B4", "B5", "P"]
_PhaseT = Literal["pilot-20", "pilot-50", "full-run"]


class RunManifest(BaseModel):
    """Provenance, configuration and aggregate metrics for one evaluation run.

    Fields
    ------
    run_id
        UUID string, unique per run (not per attempt — use ``attempt`` for that).
    dataset_id
        Parent dataset in the form ``owner/slug``.
    rule_id
        Rule being evaluated, matching ``^R-\\d{4}$``.
    variant
        Experiment variant code.
    model_id
        Model identifier string (e.g. ``"Qwen/Qwen2.5-7B-Instruct"``).
    prompt_hash
        SHA-256 (hex) of the prompt template + filled variables.
    seed
        Random seed used for generation; ``None`` if deterministic.
    code_hash
        SHA-256 (hex) of the generated code artefact; ``None`` if unavailable.
    state
        Final state-machine state for this run.
    metrics
        Aggregate metrics computed from persisted predictions (e.g. ``f1``,
        ``precision``, ``recall``).  Populated *after* the run completes.
    started_at
        UTC timestamp when the run started.
    finished_at
        UTC timestamp when the run finished; ``None`` if still in progress.
    resources
        Resource usage snapshot (CPU time, peak RAM, GPU mem, etc.).
    phase
        Experimental phase this run belongs to.
    git_commit
        Full SHA of the Git commit used for this run.
    attempt
        Monotonically increasing counter; 1 for the first attempt.
    """

    run_id: str  # UUID string — not uuid.UUID to keep JSON round-trips simple
    dataset_id: str
    rule_id: str = Field(pattern=r"^R-\d{4}$")
    variant: _VariantT
    model_id: str
    prompt_hash: str
    seed: int | None = None
    code_hash: str | None = None
    state: str
    metrics: dict[str, float] = Field(default_factory=dict)
    started_at: datetime
    finished_at: datetime | None = None
    resources: dict[str, object] = Field(default_factory=dict)
    phase: _PhaseT
    git_commit: str | None = None
    attempt: int = Field(default=1, ge=1)

    model_config = {"extra": "forbid"}
