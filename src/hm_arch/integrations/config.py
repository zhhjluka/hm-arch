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


_DEFAULT_PROJECT_DB = "./.hm_arch_agent_memory.db"
_DEFAULT_GLOBAL_DB = "~/.hm-arch/global.db"


@dataclass
class IntegrationConfig:
    """Configuration shared by all agent adapter integrations.

    Parameters
    ----------
    db_path:
        Legacy single-store override. When set, all scopes resolve to this
        path so existing single-database integrations keep working.
    global_db_path:
        SQLite path for user-wide global memory when ``scope`` is
        ``StorageScope.GLOBAL`` and ``db_path`` is unset.
    project_db_path:
        SQLite path for repository-local memory when ``scope`` is
        ``StorageScope.PROJECT`` and ``db_path`` is unset.
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
    global_db_path: str | None = None
    project_db_path: str | None = None
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
        *,
        scope: StorageScope | None = None,
    ) -> str:
        """Return the effective SQLite path for adapter operations.

        Resolution order:

        1. Explicit ``db_path`` on this config (legacy single-store mode).
        2. Scope-specific ``project_db_path`` or ``global_db_path``.
        3. ``HM_ARCH_PROJECT_DB_PATH`` / ``HM_ARCH_GLOBAL_DB_PATH``, then
           ``HM_ARCH_DB_PATH`` as a shared fallback.
        4. Built-in defaults (project: ``./.hm_arch_agent_memory.db``,
           global: ``~/.hm-arch/global.db``).

        An optional *expanduser* callable (for example ``os.path.expanduser``)
        may be supplied to expand ``~`` in global-scope paths during tests.

        Parameters
        ----------
        scope:
            When provided, resolve the path for that scope instead of
            :attr:`scope`.
        """
        if self.db_path:
            path = self.db_path
        else:
            effective_scope = scope or self.scope
            if effective_scope is StorageScope.PROJECT:
                path = (
                    self.project_db_path
                    or os.environ.get("HM_ARCH_PROJECT_DB_PATH")
                    or os.environ.get("HM_ARCH_DB_PATH")
                    or _DEFAULT_PROJECT_DB
                )
            else:
                path = (
                    self.global_db_path
                    or os.environ.get("HM_ARCH_GLOBAL_DB_PATH")
                    or os.environ.get("HM_ARCH_DB_PATH")
                    or _DEFAULT_GLOBAL_DB
                )
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
