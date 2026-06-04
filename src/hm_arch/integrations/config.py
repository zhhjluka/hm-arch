"""Integration configuration for agent adapters.

Defaults are offline-first: local SQLite storage, no remote LLM providers, and
portable project-scoped database paths.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from hm_arch.config import MemoryConfig


class StorageScope(str, Enum):
    """Where durable memory is stored relative to the host agent."""

    PROJECT = "project"
    GLOBAL = "global"


@dataclass
class IntegrationConfig:
    """Configuration shared by all agent adapter integrations.

    Parameters
    ----------
    db_path:
        SQLite database path for project-scoped storage. When ``scope`` is
        ``StorageScope.GLOBAL``, this path should point at the shared global
        database file.
    scope:
        ``project`` keeps memory isolated to the current repository;
        ``global`` uses a user-wide database path.
    recall_top_k:
        Maximum number of search hits returned by recall operations.
    max_context_chars:
        Upper bound on injected recall context size in characters.
    auto_consolidate:
        Whether consolidation may run automatically during adapter lifecycle
        events.
    consolidate_on_idle:
        Whether idle or session-boundary hooks should trigger consolidation.
    replay_sample_ratio:
        Fraction of eligible L2 episodes replayed per consolidation cycle.
    """

    db_path: str | None = None
    scope: StorageScope = StorageScope.PROJECT
    recall_top_k: int = 5
    max_context_chars: int = 8000
    auto_consolidate: bool = True
    consolidate_on_idle: bool = True
    replay_sample_ratio: float = 1.0

    def __post_init__(self) -> None:
        if self.recall_top_k < 1:
            raise ValueError("recall_top_k must be >= 1")
        if self.max_context_chars < 1:
            raise ValueError("max_context_chars must be >= 1")
        if not 0.0 < self.replay_sample_ratio <= 1.0:
            raise ValueError("replay_sample_ratio must be in (0.0, 1.0]")

    def resolve_db_path(
        self,
        expanduser: Callable[[str], str] | None = None,
    ) -> str:
        """Return the effective SQLite path for adapter operations.

        Resolution order:

        1. Explicit ``db_path`` on this config (always returned as-is).
        2. ``HM_ARCH_DB_PATH`` environment variable when ``db_path`` is empty.
        3. Configured ``db_path`` default.

        An optional *expanduser* callable (for example ``os.path.expanduser``)
        may be supplied to expand ``~`` in global-scope paths during tests.
        """
        if self.db_path:
            path = self.db_path
        else:
            path = os.environ.get("HM_ARCH_DB_PATH", "./.hm_arch_agent_memory.db")
        if expanduser is not None:
            return expanduser(path)
        return path

    def to_memory_config(self) -> MemoryConfig:
        """Build an offline-first :class:`~hm_arch.config.MemoryConfig`."""
        return MemoryConfig(
            db_path=self.resolve_db_path(),
            auto_consolidate=self.auto_consolidate,
            replay_sample_ratio=self.replay_sample_ratio,
        )
