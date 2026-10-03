"""Sandbox executor for generated code (ADR-002).

Production: Docker-based SandboxExecutor.
Testing/CI: SubprocessSandboxExecutor (no real isolation — trusted payloads only).
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SandboxResult:
    success: bool
    output: dict[str, Any]
    exit_code: int
    elapsed_ms: float
    error_message: str = ""


class SandboxSecurityError(RuntimeError):
    """Raised when a sandbox escape or policy violation is detected."""


class SandboxTimeoutError(RuntimeError):
    """Raised when the sandbox execution exceeds the time limit."""


@dataclass
class SandboxPolicy:
    timeout_seconds: int = 30
    mem_limit_mb: int = 512
    cpu_quota: float = 0.5
    pids_limit: int = 32
    network: str = "none"
    read_only_rootfs: bool = True
    user: str = "nobody"
    sandbox_image: str = "nlq-sandbox:latest"
    allowed_output_keys: frozenset[str] = frozenset({
        "result", "flagged_rows", "repair_map", "error"
    })


_DEFAULT_POLICY = SandboxPolicy()


def _make_wrapper_script(
    code: str,
    function_name: str,
    sample_path: str = "/data/sample.parquet",
) -> str:
    return (
        "import json, sys\n"
        + code
        + f"\ntry:\n"
        + f"    result = {function_name}('{sample_path}')\n"
        + "    if not isinstance(result, dict):\n"
        + "        result = {'result': result}\n"
        + "    print(json.dumps(result))\n"
        + "except Exception as exc:\n"
        + "    print(json.dumps({'error': str(exc)}))\n"
        + "    sys.exit(1)\n"
    )


class SandboxExecutor:
    """Docker-based production executor (ADR-002)."""

    def __init__(self, policy: SandboxPolicy | None = None) -> None:
        self._policy = policy or _DEFAULT_POLICY

    def execute(self, code: str, sample_path: str, function_name: str = "check") -> SandboxResult:
        p = self._policy
        wrapper = _make_wrapper_script(code, function_name)
        start = time.monotonic()
        try:
            proc = subprocess.run(
                [
                    "docker", "run", "--rm",
                    "--network", p.network,
                    "--user", p.user,
                    "--read-only",
                    "--tmpfs", "/tmp:size=64m",
                    "--memory", f"{p.mem_limit_mb}m",
                    "--memory-swap", f"{p.mem_limit_mb}m",
                    "--cpu-period", "100000",
                    "--cpu-quota", str(int(p.cpu_quota * 100_000)),
                    "--pids-limit", str(p.pids_limit),
                    "--volume", f"{sample_path}:/data/sample.parquet:ro",
                    p.sandbox_image,
                    "python", "-c", wrapper,
                ],
                capture_output=True, text=True, timeout=p.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            raise SandboxTimeoutError(f"Exceeded {p.timeout_seconds}s limit.")
        except FileNotFoundError:
            elapsed = (time.monotonic() - start) * 1000
            return SandboxResult(success=False, output={}, exit_code=-1,
                                 elapsed_ms=elapsed, error_message="Docker not found.")
        elapsed = (time.monotonic() - start) * 1000
        if proc.returncode != 0:
            return SandboxResult(success=False, output={}, exit_code=proc.returncode,
                                 elapsed_ms=elapsed, error_message=proc.stderr[:2048])
        try:
            raw = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return SandboxResult(success=False, output={}, exit_code=proc.returncode,
                                 elapsed_ms=elapsed,
                                 error_message=f"Non-JSON: {proc.stdout[:256]}")
        filtered = {k: v for k, v in raw.items() if k in p.allowed_output_keys}
        return SandboxResult(success=True, output=filtered, exit_code=0, elapsed_ms=elapsed)


class SubprocessSandboxExecutor:
    """Subprocess-based executor for unit testing ONLY. NOT for production."""

    def __init__(self, policy: SandboxPolicy | None = None) -> None:
        self._policy = policy or SandboxPolicy(timeout_seconds=5)

    def execute(self, code: str, sample_path: str = "", function_name: str = "check") -> SandboxResult:
        wrapper = _make_wrapper_script(code, function_name, sample_path=sample_path)
        start = time.monotonic()
        try:
            proc = subprocess.run(
                ["python", "-c", wrapper],
                capture_output=True, text=True, timeout=self._policy.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            elapsed = (time.monotonic() - start) * 1000
            return SandboxResult(success=False, output={}, exit_code=-1,
                                 elapsed_ms=elapsed, error_message="TimeoutExpired")
        elapsed = (time.monotonic() - start) * 1000
        if proc.returncode != 0:
            return SandboxResult(success=False, output={}, exit_code=proc.returncode,
                                 elapsed_ms=elapsed, error_message=proc.stderr[:2048])
        try:
            raw = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return SandboxResult(success=False, output={}, exit_code=0,
                                 elapsed_ms=elapsed, error_message=f"Non-JSON: {proc.stdout[:256]}")
        return SandboxResult(success=True, output=raw, exit_code=0, elapsed_ms=elapsed)
