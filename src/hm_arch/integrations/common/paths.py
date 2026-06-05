"""Database path resolution and memory store helpers for agent hooks."""

from __future__ import annotations

import os
from pathlib import Path

from hm_arch import HMArch, MemoryConfig

from ..config import IntegrationConfig, StorageScope


def resolve_db_path(
    explicit: str | None = None,
    *,
    config: IntegrationConfig | None = None,
    scope: StorageScope | None = None,
) -> str:
    """Return the SQLite path for hook scripts.

    Priority when *explicit* is ``None``:

    1. Scope-aware resolution from *config* (or a default
       :class:`~hm_arch.integrations.config.IntegrationConfig`).
    2. ``HM_ARCH_DB_PATH`` env var for project scope only when no config paths
       are set (handled inside :meth:`IntegrationConfig.resolve_db_path`).

    An explicit *explicit* path always wins for backward compatibility.
    """
    if explicit is not None:
        return explicit
    if config is None:
        env_path = os.environ.get("HM_ARCH_DB_PATH")
        if env_path:
            return env_path
        return str(Path.cwd() / ".hm_arch_agent_memory.db")
    return config.resolve_db_path(scope=scope)


def open_memory(
    db_path: str | None = None,
    *,
    config: IntegrationConfig | None = None,
    scope: StorageScope | None = None,
    replay_sample_ratio: float | None = None,
) -> HMArch:
    """Open an :class:`~hm_arch.core.HMArch` store for hook handlers."""
    if config is not None:
        path = config.resolve_db_path(scope=scope)
        ratio = (
            replay_sample_ratio
            if replay_sample_ratio is not None
            else config.replay_sample_ratio
        )
    else:
        path = resolve_db_path(db_path)
        ratio = replay_sample_ratio if replay_sample_ratio is not None else 1.0

    memory_config = MemoryConfig(db_path=path, replay_sample_ratio=ratio)
    return HMArch(config=memory_config)
