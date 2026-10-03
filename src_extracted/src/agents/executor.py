"""Executor agent — runs code in the sandbox and returns execution results.

Pipeline position: EXECUTED → TESTED
Integrates with SandboxExecutor (Docker) or SubprocessSandboxExecutor (tests).
"""
from __future__ import annotations

import time
from typing import Any

from agents.sandbox import SandboxExecutor, SubprocessSandboxExecutor, SandboxPolicy
from models.agent_result import AgentResult
from orchestration.state_machine import PipelineState
from utils.ids import hash_dict, hash_content, new_trace_id


def execute_code(
    code_payload: dict[str, Any],
    sample_path: str,
    use_subprocess: bool = False,
    trace_id: str | None = None,
) -> AgentResult:
    """Execute generated code in the sandbox.

    Parameters
    ----------
    code_payload:
        Dict with key "code" containing Python source. Produced by T4.7.
    sample_path:
        Path to the Parquet sample for this dataset.
    use_subprocess:
        If True, use SubprocessSandboxExecutor (test/CI only).
        If False (default), use Docker SandboxExecutor (production).
    trace_id:
        Trace identifier.

    Returns
    -------
    AgentResult with execution results in payload["execution_result"].
    """
    tid = trace_id or new_trace_id()
    start = time.monotonic()
    agent_id = "executor-v1"
    code = code_payload.get("code", "")
    input_hash = hash_content(code)

    try:
        if use_subprocess:
            sandbox = SubprocessSandboxExecutor(SandboxPolicy(timeout_seconds=10))
        else:
            sandbox = SandboxExecutor()  # type: ignore[assignment]

        exec_result = sandbox.execute(code=code, sample_path=sample_path)
        elapsed = (time.monotonic() - start) * 1000
        payload = code_payload.copy()
        payload["execution_result"] = {
            "success": exec_result.success,
            "output": exec_result.output,
            "exit_code": exec_result.exit_code,
            "elapsed_ms": exec_result.elapsed_ms,
            "error_message": exec_result.error_message,
        }

        if not exec_result.success:
            return AgentResult(
                status="HUMAN_REVIEW" if exec_result.exit_code != -1 else "ERROR",
                payload=payload,
                evidence=[],
                diagnostics=[{
                    "level": "error",
                    "message": exec_result.error_message or "Execution failed",
                }],
                trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
                from_state=PipelineState.EXECUTED,
                to_state=PipelineState.REPAIRED,
                input_hash=input_hash, output_hash=hash_dict({"success": False}),
            )

        return AgentResult(
            status="OK", payload=payload, evidence=[], diagnostics=[],
            trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
            from_state=PipelineState.EXECUTED,
            to_state=PipelineState.TESTED,
            input_hash=input_hash, output_hash=hash_dict(exec_result.output),
        )

    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return AgentResult(
            status="ERROR", payload=code_payload, evidence=[],
            diagnostics=[{"level": "error", "message": str(exc)}],
            trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
            from_state=PipelineState.EXECUTED,
            to_state=PipelineState.FAILED,
            input_hash=input_hash, output_hash=hash_dict({}),
        )
