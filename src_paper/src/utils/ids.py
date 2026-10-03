"""Utilities for generating and validating unique identifiers and hashes.

Rules:
- run_id and trace_id are UUID4 strings (no braces, lower-case).
- Content hashes are SHA-256 hex digests of UTF-8 encoded JSON.
- Never log the raw content being hashed; only log the hash.
"""
from __future__ import annotations

import hashlib
import json
import uuid


def new_run_id() -> str:
    """Generate a new UUID4 run identifier."""
    return str(uuid.uuid4())


def new_trace_id() -> str:
    """Generate a new UUID4 trace identifier."""
    return str(uuid.uuid4())


def hash_content(content: str | bytes) -> str:
    """Return the SHA-256 hex digest of the given content.

    Parameters
    ----------
    content:
        A string (encoded as UTF-8) or raw bytes.

    Returns
    -------
    64-character lowercase hex string.
    """
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def hash_dict(data: dict) -> str:  # type: ignore[type-arg]
    """Return a deterministic SHA-256 hash of a JSON-serialisable dict.

    The dict is serialised with sorted keys to ensure stability across
    Python sessions.
    """
    serialised = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hash_content(serialised)


def hash_file(path: str) -> str:
    """Return the SHA-256 hex digest of a file on disk.

    Reads the file in 64 KB chunks to avoid loading large files into RAM.

    Parameters
    ----------
    path:
        Path to the file.

    Returns
    -------
    64-character lowercase hex string.
    """
    digest = hashlib.sha256()
    chunk_size = 65_536  # 64 KB
    with open(path, "rb") as fh:
        while chunk := fh.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
