"""Public interface for the ``models`` package.

Import all models from here so that downstream code does not need to know the
internal module layout.

Usage::

    from models import IR, DatasetRecord, RuleRecord, AgentResult, RunManifest, Prediction
    from models.ir import IRScope, IRLogic, IRAction
"""
from __future__ import annotations

from .agent_result import AgentResult
from .dataset import DatasetRecord
from .ir import IR, IRAction, IRLogic, IRScope
from .prediction import Prediction
from .rule import RuleRecord
from .run_manifest import RunManifest

__all__ = [
    "AgentResult",
    "DatasetRecord",
    "IR",
    "IRAction",
    "IRLogic",
    "IRScope",
    "Prediction",
    "RuleRecord",
    "RunManifest",
]
