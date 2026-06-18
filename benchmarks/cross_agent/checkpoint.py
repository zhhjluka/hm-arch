"""Checkpoint and resume support for long benchmark runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .types import BenchmarkRunConfig, QueryRecord, RunPhase


def checkpoint_path(storage_dir: Path) -> Path:
    return storage_dir / "checkpoint.json"


def write_checkpoint(
    storage_dir: Path,
    *,
    run_id: str,
    phases_completed: list[str],
    completed_query_ids: list[str],
    queries: list[QueryRecord],
    config: BenchmarkRunConfig | None = None,
    status: str = "in_progress",
    error: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "run_id": run_id,
        "status": status,
        "error": error,
        "config": config.to_dict() if config is not None else None,
        "phases_completed": phases_completed,
        "completed_query_ids": completed_query_ids,
        "queries": [q.to_dict() for q in queries],
    }
    path = checkpoint_path(storage_dir)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_checkpoint(storage_dir: Path) -> dict[str, Any] | None:
    path = checkpoint_path(storage_dir)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def phase_done(phases_completed: list[str], phase: RunPhase) -> bool:
    return phase.value in phases_completed


def mark_phase(phases_completed: list[str], phase: RunPhase) -> None:
    if phase.value not in phases_completed:
        phases_completed.append(phase.value)
