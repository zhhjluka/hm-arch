"""Shared HM-Arch storage paths for benchmark backends and agent hooks."""

from __future__ import annotations

from pathlib import Path


def hm_arch_db_path(storage_dir: Path) -> Path:
    """Canonical per-run HM-Arch SQLite file used by backend ingest and agent hooks."""
    return storage_dir / "hm_arch.db"


def hm_arch_db_path_str(storage_dir: Path) -> str:
    return str(hm_arch_db_path(storage_dir))
