"""AST guard — validates generated Python code before sandbox execution.

The AST guard performs static analysis to block dangerous patterns:
- Denied imports (os.system, subprocess, socket, etc.)
- Denied built-ins (__import__, eval, exec, compile)
- Network access attempts
- File writes outside /tmp

IMPORTANT: The AST guard is a first barrier, NOT a sandbox.
A function that passes AST may still be semantically incorrect.
It must be followed by sandbox execution and functional tests.
"""
from __future__ import annotations

import ast
import time
from typing import Any

from models.agent_result import AgentResult
from orchestration.state_machine import PipelineState
from utils.ids import hash_dict, hash_content, new_trace_id


# ---------------------------------------------------------------------------
# Denylist
# ---------------------------------------------------------------------------

_DENIED_IMPORTS: frozenset[str] = frozenset({
    "os", "subprocess", "socket", "requests", "urllib", "http",
    "ftplib", "smtplib", "telnetlib", "poplib", "imaplib",
    "shutil", "pathlib", "glob",  # file system traversal
    "pickle", "marshal",  # deserialization
    "__builtins__",
})

_DENIED_BUILTINS: frozenset[str] = frozenset({
    "__import__", "eval", "exec", "compile",
    "open", "input", "breakpoint",
})

# Allowed import names (pandas, json, re, math, etc.)
_ALLOWED_IMPORTS: frozenset[str] = frozenset({
    "pandas", "pd", "json", "re", "math", "datetime", "decimal",
    "collections", "itertools", "functools", "typing", "dataclasses",
    "enum", "abc", "copy", "operator",
})

# Methods deprecated/removed in pandas 2.0+ that should be auto-corrected
# The AST guard flags these so the Repair Agent knows to fix them.
_DEPRECATED_METHODS: dict[str, str] = {
    "iteritems": "items",        # Series.iteritems() → Series.items()
    "iterrows_":  "iterrows",    # no-op, keep for completeness
    "append":     "pd.concat",   # DataFrame.append() → pd.concat()
    "swaplevel":  "swaplevel",   # no change but flag for review
}


# ---------------------------------------------------------------------------
# Visitor
# ---------------------------------------------------------------------------

class _DenylistVisitor(ast.NodeVisitor):
    """AST node visitor that collects policy violations."""

    def __init__(self) -> None:
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            module_root = alias.name.split(".")[0]
            if module_root in _DENIED_IMPORTS:
                self.violations.append(f"Denied import: '{alias.name}' (line {node.lineno})")
            elif module_root not in _ALLOWED_IMPORTS:
                self.violations.append(
                    f"Unknown import: '{alias.name}' (line {node.lineno}) — "
                    "only allowed modules are permitted"
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        module_root = module.split(".")[0]
        if module_root in _DENIED_IMPORTS:
            self.violations.append(f"Denied import from: '{module}' (line {node.lineno})")
        elif module_root and module_root not in _ALLOWED_IMPORTS:
            self.violations.append(
                f"Unknown import from: '{module}' (line {node.lineno})"
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Check for denied built-in calls
        if isinstance(node.func, ast.Name) and node.func.id in _DENIED_BUILTINS:
            self.violations.append(
                f"Denied built-in call: '{node.func.id}' (line {node.lineno})"
            )
        # Check for denied attribute calls (os.system, subprocess.run, etc.)
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                full = f"{node.func.value.id}.{node.func.attr}"
                if node.func.value.id in _DENIED_IMPORTS:
                    self.violations.append(
                        f"Denied call: '{full}' (line {node.lineno})"
                    )

        # Check for deprecated pandas methods (BUG-012: iteritems, etc.)
        if isinstance(node.func, ast.Attribute):
            if node.func.attr in _DEPRECATED_METHODS:
                replacement = _DEPRECATED_METHODS[node.func.attr]
                self.violations.append(
                    f"Deprecated pandas method: '.{node.func.attr}()' at line {node.lineno} "
                    f"— use '.{replacement}()' instead (removed in pandas 2.0)"
                )

        self.generic_visit(node)


# ---------------------------------------------------------------------------
# Guard function
# ---------------------------------------------------------------------------

def ast_check(
    code_payload: dict[str, Any],
    trace_id: str | None = None,
) -> AgentResult:
    """Run the AST guard on generated code.

    Parameters
    ----------
    code_payload:
        Dict with key "code" containing Python source code.
    trace_id:
        Trace identifier.

    Returns
    -------
    AgentResult:
    - status="OK" if code passes all checks → to_state=EXECUTED
    - status="HUMAN_REVIEW" if violations found → to_state=REPAIRED
    - status="ERROR" if code cannot be parsed
    """
    tid = trace_id or new_trace_id()
    start = time.monotonic()
    agent_id = "ast-guard-v1"
    code = code_payload.get("code", "")
    input_hash = hash_content(code)

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        elapsed = (time.monotonic() - start) * 1000
        return AgentResult(
            status="ERROR",
            payload=code_payload,
            evidence=[],
            diagnostics=[{"level": "error", "message": f"SyntaxError: {exc}"}],
            trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
            from_state=PipelineState.AST_VALID,
            to_state=PipelineState.REPAIRED,
            input_hash=input_hash, output_hash=hash_dict({}),
        )

    visitor = _DenylistVisitor()
    visitor.visit(tree)
    elapsed = (time.monotonic() - start) * 1000

    if visitor.violations:
        payload = code_payload.copy()
        payload["ast_violations"] = visitor.violations
        return AgentResult(
            status="HUMAN_REVIEW",
            payload=payload,
            evidence=[],
            diagnostics=[
                {"level": "error", "message": v} for v in visitor.violations
            ],
            trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
            from_state=PipelineState.AST_VALID,
            to_state=PipelineState.REPAIRED,
            input_hash=input_hash, output_hash=hash_dict({"violations": visitor.violations}),
        )

    payload = code_payload.copy()
    payload["ast_violations"] = []
    return AgentResult(
        status="OK", payload=payload, evidence=[], diagnostics=[],
        trace_id=tid, elapsed_ms=elapsed, agent_id=agent_id,
        from_state=PipelineState.AST_VALID,
        to_state=PipelineState.EXECUTED,
        input_hash=input_hash, output_hash=hash_content(code),
    )
