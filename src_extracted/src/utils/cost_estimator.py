"""
cost_estimator.py — Estimador de costos y recursos para el NLQ Quality Benchmark.

Propósito: calcular estimaciones conservadoras de GPU-hours, almacenamiento,
llamadas API y tiempo de reloj para cada fase del experimento. Además expone
una *gate* que bloquea la ejecución del full-run si no existe una aprobación
de presupuesto registrada en configs/budget_approval.yaml.

Nota de integridad: las estimaciones son aproximaciones conservadoras; el uso
real variará según hardware, dataset y configuración del modelo.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Constantes de estimación (asunciones conservadoras del spec)
# ---------------------------------------------------------------------------

# Inferencia Qwen2.5-7B-Instruct en A100 GPU
_SECONDS_PER_RULE_INFERENCE: float = 2.0          # segundos por regla
_TOKENS_PER_RULE_AVG: int = 1_000                 # tokens de salida por regla

# Variantes del experimento: B0–B5 + P = 7; seeds de entrenamiento = 3
_N_VARIANTS_DEFAULT: int = 7
_N_SEEDS_DEFAULT: int = 3

# Entrenamiento QLoRA (NL→IR): ~1 h por seed en A100, 3 epochs sobre 600 reglas
_QLORA_TRAINING_HOURS_PER_SEED: float = 1.0

# Almacenamiento
_BYTES_PER_PARQUET_ROW_AVG: int = 1_024           # 1 KB por fila Parquet
_PARQUET_ROWS_PER_RULE: int = 10                  # filas por predicción
_PROFILE_DATA_GB_PER_200_DATASETS: float = 50.0   # perfiles DuckDB + raw cache
_OVERHEAD_MULTIPLIER: float = 1.5                 # 50 % overhead (logs, checkpoints…)

# Kaggle API
_METADATA_CALLS_PER_DATASET: int = 10             # búsqueda + metadatos + license


# ---------------------------------------------------------------------------
# Modelos de datos
# ---------------------------------------------------------------------------

class ResourceEstimate(BaseModel):
    """Estimación de recursos para una fase del benchmark."""

    phase: str = Field(..., description="Nombre de la fase (pilot-20, pilot-50, full-run)")
    n_datasets: int = Field(..., ge=1)
    n_rules: int = Field(..., ge=1)
    n_variants: int = Field(..., ge=1, description="Número de variantes de modelo (B0–B5, P)")
    n_seeds: int = Field(..., ge=1, description="Seeds de entrenamiento QLoRA")
    n_repairs_max: int = Field(3, ge=0, description="Máximo de intentos de reparación por regla")

    tokens_per_rule_avg: int = Field(
        _TOKENS_PER_RULE_AVG,
        description="Tokens de salida promedio por regla × variante × seed",
    )

    # Tiempos
    gpu_hours_estimate: float = Field(..., description="GPU-hours totales estimadas (A100)")
    wall_clock_hours_estimate: float = Field(
        ..., description="Horas de reloj estimadas (sin paralelismo)"
    )

    # Almacenamiento
    storage_gb_estimate: float = Field(..., description="GB de almacenamiento estimados")

    # API
    kaggle_api_calls_estimate: int = Field(
        ..., description="Llamadas a la API de Kaggle estimadas"
    )

    notes: str = Field("", description="Notas adicionales sobre las asunciones")


# ---------------------------------------------------------------------------
# Clase estimadora
# ---------------------------------------------------------------------------

class CostEstimator:
    """
    Calcula estimaciones conservadoras de recursos para cada fase.

    Las asunciones base se documentan en reports/resource_estimates.md.
    Cualquier cambio de asunción debe reflejarse en ambos lugares.
    """

    def estimate(
        self,
        phase: str,
        n_datasets: int,
        n_rules: int,
        n_variants: int = _N_VARIANTS_DEFAULT,
        n_seeds: int = _N_SEEDS_DEFAULT,
        n_repairs_max: int = 3,
        tokens_per_rule_avg: int = _TOKENS_PER_RULE_AVG,
        notes: str = "",
    ) -> ResourceEstimate:
        """
        Calcula la estimación de recursos para una fase dada.

        Parameters
        ----------
        phase:
            Identificador de fase, p. ej. "pilot-20", "pilot-50" o "full-run".
        n_datasets:
            Número de datasets en la fase.
        n_rules:
            Número de reglas canónicas en la fase.
        n_variants:
            Número de variantes de modelo a evaluar (B0–B5, P = 7 por defecto).
        n_seeds:
            Número de seeds para entrenamiento QLoRA (3 por defecto).
        n_repairs_max:
            Número máximo de intentos de reparación por regla (3 por defecto).
        tokens_per_rule_avg:
            Tokens de salida promedio por llamada de inferencia.
        notes:
            Notas adicionales libres.

        Returns
        -------
        ResourceEstimate con campos calculados de forma conservadora.
        """
        # --- Inferencia ---
        # Cada regla es evaluada por n_variants × n_seeds; reparaciones añaden
        # hasta n_repairs_max llamadas adicionales por regla.
        total_inference_calls = n_rules * n_variants * n_seeds * (1 + n_repairs_max)
        inference_seconds = total_inference_calls * _SECONDS_PER_RULE_INFERENCE
        inference_gpu_hours = inference_seconds / 3_600.0

        # --- Entrenamiento QLoRA ---
        # Dos adaptadores: NL→código y NL→IR; cada uno × n_seeds
        qlora_training_gpu_hours = 2 * n_seeds * _QLORA_TRAINING_HOURS_PER_SEED

        total_gpu_hours = round(inference_gpu_hours + qlora_training_gpu_hours, 2)

        # Wall-clock asume uso secuencial (cota superior conservadora)
        wall_clock_hours = round(total_gpu_hours * 1.1, 2)  # 10 % overhead I/O

        # --- Almacenamiento ---
        # Predicciones en Parquet
        prediction_bytes = (
            n_rules
            * n_variants
            * n_seeds
            * _PARQUET_ROWS_PER_RULE
            * _BYTES_PER_PARQUET_ROW_AVG
        )
        prediction_gb = prediction_bytes / (1024 ** 3)

        # Perfiles de datasets (escala proporcional a 200 datasets de referencia)
        profile_gb = (n_datasets / 200.0) * _PROFILE_DATA_GB_PER_200_DATASETS

        storage_gb = round((prediction_gb + profile_gb) * _OVERHEAD_MULTIPLIER, 2)

        # --- Kaggle API ---
        # 1 descarga + metadata_calls por dataset
        kaggle_calls = n_datasets * (1 + _METADATA_CALLS_PER_DATASET)

        return ResourceEstimate(
            phase=phase,
            n_datasets=n_datasets,
            n_rules=n_rules,
            n_variants=n_variants,
            n_seeds=n_seeds,
            n_repairs_max=n_repairs_max,
            tokens_per_rule_avg=tokens_per_rule_avg,
            gpu_hours_estimate=total_gpu_hours,
            wall_clock_hours_estimate=wall_clock_hours,
            storage_gb_estimate=storage_gb,
            kaggle_api_calls_estimate=kaggle_calls,
            notes=notes,
        )


# ---------------------------------------------------------------------------
# Aprobación de presupuesto
# ---------------------------------------------------------------------------

class BudgetNotApprovedError(RuntimeError):
    """
    Se lanza cuando se intenta iniciar el full-run sin aprobación de presupuesto
    registrada en configs/budget_approval.yaml.
    """


def check_budget_approval(budget_file: str = "configs/budget_approval.yaml") -> bool:
    """
    Lee el archivo de aprobación de presupuesto y verifica que:

    1. ``approved`` es ``true``.
    2. ``approved_by`` no está vacío.
    3. ``approved_at`` no está vacío.

    Parameters
    ----------
    budget_file:
        Ruta al archivo YAML de aprobación. Por defecto
        ``configs/budget_approval.yaml`` relativo al directorio de trabajo.

    Returns
    -------
    ``True`` si todas las condiciones se cumplen.

    Raises
    ------
    BudgetNotApprovedError
        Si alguna condición falla o el archivo no existe / no puede leerse.
    FileNotFoundError
        Si el archivo no existe (propagado como BudgetNotApprovedError con mensaje claro).
    """
    path = Path(budget_file)

    if not path.exists():
        raise BudgetNotApprovedError(
            f"Archivo de aprobación de presupuesto no encontrado: '{path}'. "
            "Crea el archivo desde la plantilla en configs/budget_approval.yaml "
            "y completa todos los campos antes de ejecutar el full-run."
        )

    try:
        with path.open("r", encoding="utf-8") as fh:
            data: dict = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        raise BudgetNotApprovedError(
            f"El archivo de presupuesto '{path}' no es YAML válido: {exc}"
        ) from exc

    approved: bool = bool(data.get("approved", False))
    approved_by: str = str(data.get("approved_by", "")).strip()
    approved_at: str = str(data.get("approved_at", "")).strip()

    errors: list[str] = []
    if not approved:
        errors.append("'approved' debe ser true")
    if not approved_by:
        errors.append("'approved_by' no puede estar vacío")
    if not approved_at:
        errors.append("'approved_at' no puede estar vacío")

    if errors:
        raise BudgetNotApprovedError(
            f"Presupuesto no aprobado en '{path}'. Problemas: "
            + "; ".join(errors)
            + ". Completa configs/budget_approval.yaml antes de ejecutar make full-run."
        )

    return True


def gate_full_run(
    budget_file: str = "configs/budget_approval.yaml",
) -> None:
    """
    Gate obligatoria antes de cualquier fase de full-run (T9.x).

    Llama a :func:`check_budget_approval` y propaga
    :exc:`BudgetNotApprovedError` si la aprobación no está en orden.

    Uso típico::

        from src.utils.cost_estimator import gate_full_run
        gate_full_run()          # lanza si no hay aprobación
        # ... código de full-run

    Parameters
    ----------
    budget_file:
        Ruta al YAML de aprobación. Relativo al CWD del proceso invocador.
    """
    check_budget_approval(budget_file)
