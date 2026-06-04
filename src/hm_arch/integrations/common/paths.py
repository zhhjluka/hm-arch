"""Database path resolution and memory store helpers for agent hooks."""

from __future__ import annotations

import os
from pathlib import Path

from hm_arch import HMArch, MemoryConfig


def resolve_db_path(explicit: str | None = None) -> str:
    """Return the SQLite path for hook scripts.

    Priority: *explicit* argument, ``HM_ARCH_DB_PATH`` env var, then
    ``./.hm_arch_agent_memory.db`` under the current working directory.
    """
    if explicit is not None:
        return explicit
    env_path = os.environ.get("HM_ARCH_DB_PATH")
    if env_path:
        return env_path
    return str(Path.cwd() / ".hm_arch_agent_memory.db")


def open_memory(
    db_path: str | None = None,
    *,
    replay_sample_ratio: float = 1.0,
) -> HMArch:
    """Open an :class:`~hm_arch.core.HMArch` store for hook handlers."""
    path = resolve_db_path(db_path)
    config = MemoryConfig(db_path=path, replay_sample_ratio=replay_sample_ratio)
    return HMArch(config=config)
