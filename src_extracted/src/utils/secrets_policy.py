"""Secrets policy: detect and block commits of tokens or raw data.

These utilities are called from pre-commit hooks and from the CI security job.
They never read the actual secret values — only check for their presence.
"""
from __future__ import annotations

import re
from pathlib import Path


# Patterns that indicate a secret may be present in a file
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'(?i)(hf_token|huggingface_token)\s*=\s*["\'][^"\']{8,}["\']'),
    re.compile(r'(?i)(kaggle_key|kaggle_username)\s*=\s*["\'][^"\']{3,}["\']'),
    re.compile(r'(?i)(api_key|secret_key|password|bearer)\s*=\s*["\'][^"\']{8,}["\']'),
    re.compile(r'hf_[A-Za-z0-9]{20,}'),  # HuggingFace token pattern
    re.compile(r'(?i)authorization:\s*bearer\s+[A-Za-z0-9\-_\.]{20,}'),
]

# File extensions that should never be committed as raw data
_BLOCKED_EXTENSIONS: frozenset[str] = frozenset({
    ".safetensors", ".bin", ".gguf", ".pt", ".pth", ".ckpt",
    ".parquet", ".csv", ".tsv", ".jsonl",
})

# Paths that are always allowed regardless of extension (spec/config files)
_ALLOWED_PATH_PREFIXES: tuple[str, ...] = (
    ".kiro/", "schemas/", "docs/", "reports/", "configs/", ".github/",
)


class SecretDetectedError(ValueError):
    """Raised when a potential secret is found in a file."""


class RawDataCommitError(ValueError):
    """Raised when raw data files are staged for commit."""


def scan_file_for_secrets(path: str) -> list[str]:
    """Scan a text file for potential secret patterns.

    Parameters
    ----------
    path:
        Path to the file to scan.

    Returns
    -------
    List of warning messages (empty if no secrets detected).
    Does not raise — callers decide whether to block.
    """
    warnings: list[str] = []
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return warnings
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            # Report the pattern name, not the matched value
            warnings.append(
                f"Potential secret detected in '{path}' matching pattern: "
                f"{pattern.pattern[:60]}..."
            )
    return warnings


def check_staged_files(staged_paths: list[str]) -> list[str]:
    """Check a list of staged file paths for secrets and raw data.

    Parameters
    ----------
    staged_paths:
        List of file paths about to be committed.

    Returns
    -------
    List of blocking violation messages (empty = safe to commit).
    """
    violations: list[str] = []
    for path in staged_paths:
        p = Path(path)
        # Check for raw data extensions
        if p.suffix in _BLOCKED_EXTENSIONS:
            if not any(path.replace("\\", "/").startswith(prefix) for prefix in _ALLOWED_PATH_PREFIXES):
                violations.append(
                    f"Raw data file staged for commit: '{path}' "
                    f"(extension '{p.suffix}' is blocked). "
                    "Move to the external cache or add to .gitignore."
                )
        # Scan text files for secrets
        if p.suffix in {".py", ".yaml", ".yml", ".toml", ".json", ".env", ".txt", ".sh"}:
            secret_warnings = scan_file_for_secrets(path)
            violations.extend(secret_warnings)
    return violations
