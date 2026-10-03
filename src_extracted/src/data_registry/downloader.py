"""Resumable dataset downloader with SHA-256 manifests (ADR-004).

Downloads Kaggle datasets to ~/.nlq_benchmark_cache/ (never to the repo).
Credentials: KAGGLE_API_TOKEN, KAGGLE_USERNAME+KAGGLE_KEY, or ~/.kaggle/kaggle.json.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.ids import hash_file
from data_registry.kaggle_client import _check_credentials


DEFAULT_CACHE_DIR: Path = Path.home() / ".nlq_benchmark_cache"


class DownloadError(RuntimeError):
    """Raised when a download fails."""


def _dataset_cache_dir(owner: str, slug: str, version: str,
                       cache_root: Path = DEFAULT_CACHE_DIR) -> Path:
    return cache_root / owner / slug / f"v{version}"


def _manifest_path(cache_dir: Path) -> Path:
    return cache_dir / "manifest.json"


def load_manifest(owner: str, slug: str, version: str,
                  cache_root: Path = DEFAULT_CACHE_DIR) -> dict[str, Any] | None:
    path = _manifest_path(_dataset_cache_dir(owner, slug, version, cache_root))
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def verify_manifest(owner: str, slug: str, version: str,
                    cache_root: Path = DEFAULT_CACHE_DIR) -> bool:
    manifest = load_manifest(owner, slug, version, cache_root)
    if manifest is None:
        return False
    raw_dir = _dataset_cache_dir(owner, slug, version, cache_root) / "raw"
    for entry in manifest.get("files", []):
        fp = raw_dir / entry["filename"]
        if not fp.exists():
            return False
        if hash_file(str(fp)) != entry["sha256"]:
            return False
    return True


def _write_manifest(cache_dir: Path, owner: str, slug: str,
                    version: str, file_entries: list[dict[str, Any]]) -> None:
    manifest: dict[str, Any] = {
        "owner": owner, "slug": slug, "version": version,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": file_entries,
    }
    _manifest_path(cache_dir).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def download_dataset(
    owner: str,
    slug: str,
    version: str = "latest",
    cache_root: Path = DEFAULT_CACHE_DIR,
    force: bool = False,
) -> Path:
    """Download a Kaggle dataset to the local cache.

    Supports KAGGLE_API_TOKEN, KAGGLE_USERNAME+KAGGLE_KEY, and ~/.kaggle/kaggle.json.
    Downloads to cache_root/owner/slug/vversion/raw/.
    Skips if manifest exists and hashes match (resumable).
    """
    _check_credentials()

    cache_dir = _dataset_cache_dir(owner, slug, version, cache_root)
    raw_dir = cache_dir / "raw"

    if not force and verify_manifest(owner, slug, version, cache_root):
        return raw_dir

    raw_dir.mkdir(parents=True, exist_ok=True)

    # Use Kaggle API directly — supports all credential formats
    try:
        import kaggle  # type: ignore[import]
        api = kaggle.KaggleApi()
        api.authenticate()
        api.dataset_download_files(
            f"{owner}/{slug}",
            path=str(raw_dir),
            unzip=True,
        )
    except ImportError as exc:
        raise DownloadError(
            "kaggle package not installed. Run: pip install kaggle"
        ) from exc
    except Exception as exc:
        raise DownloadError(f"Download failed for {owner}/{slug}: {exc}") from exc

    # Build manifest
    file_entries: list[dict[str, Any]] = []
    for fp in sorted(raw_dir.rglob("*")):
        if fp.is_file():
            file_entries.append({
                "filename": str(fp.relative_to(raw_dir)),
                "size_bytes": fp.stat().st_size,
                "sha256": hash_file(str(fp)),
            })

    _write_manifest(cache_dir, owner, slug, version, file_entries)
    return raw_dir


def _copy_to_raw(source_dir: Path, raw_dir: Path) -> None:
    for item in source_dir.rglob("*"):
        if item.is_file():
            dest = raw_dir / item.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(item), str(dest))
