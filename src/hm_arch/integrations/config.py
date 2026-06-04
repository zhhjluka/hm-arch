"""Integration configuration for agent adapters.

Defaults are offline-first: no LLM providers, project-scoped SQLite storage,
and local deterministic memory behavior.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from hm_arch.config import MemoryConfig

_VALID_PRESETS = frozenset({"code_agent", "chat_agent", "research_agent"})


class IntegrationScope(str, Enum):
    """Where the integration stores durable memory."""

    PROJECT = "project"
    GLOBAL = "global"


@dataclass
class IntegrationConfig:
    """Configuration shared by all agent adapters.

    Parameters
    ----------
    db_path:
        SQLite database path. For :attr:`scope` ``"project"``, this is typically
        a repository-local file. For ``"global"``, a user-level path such as
        ``~/.hm-arch/memory.db``.
    scope:
        ``"project"`` (default) or ``"global"``.
    recall_top_k:
        Maximum number of search hits considered for recall.
    max_context_chars:
        Maximum characters returned in recall context text.
    consolidation_enabled:
        When ``False``, consolidate requests succeed without running sleep
        consolidation (useful for dry-run hooks).
    replay_sample_ratio:
        Fraction of eligible L2 episodes replayed per consolidation cycle.
    memory_preset:
        Optional :class:`~hm_arch.config.MemoryConfig` preset name.
    enable_llm_providers:
        Opt-in remote providers. Defaults to ``False`` for offline-first use.
    provider_fallback_to_local:
        Fall back to local heuristics when provider calls fail.
    """

    db_path: str = "./.hm_arch_agent_memory.db"
    scope: IntegrationScope = IntegrationScope.PROJECT
    recall_top_k: int = 5
    max_context_chars: int = 8192
    consolidation_enabled: bool = True
    replay_sample_ratio: float = 0.20
    memory_preset: str | None = None
    enable_llm_providers: bool = False
    provider_fallback_to_local: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.scope, str):
            self.scope = IntegrationScope(self.scope)
        self.validate()

    def validate(self) -> None:
        """Raise :class:`ValueError` when configuration is invalid."""
        if not self.db_path or not str(self.db_path).strip():
            raise ValueError("db_path must be a non-empty string")
        if self.recall_top_k < 1:
            raise ValueError("recall_top_k must be >= 1")
        if self.max_context_chars < 0:
            raise ValueError("max_context_chars must be >= 0")
        if not 0.0 < self.replay_sample_ratio <= 1.0:
            raise ValueError("replay_sample_ratio must be in (0, 1]")
        if self.memory_preset is not None and self.memory_preset not in _VALID_PRESETS:
            raise ValueError(
                f"Unknown memory_preset {self.memory_preset!r}. "
                f"Valid presets: {sorted(_VALID_PRESETS)}"
            )

    def resolve_db_path(self, *, cwd: Path | None = None) -> str:
        """Return the effective SQLite path for this integration.

        Priority: ``HM_ARCH_DB_PATH`` environment variable, then
        :attr:`db_path` (expanded for global scope).
        """
        env_path = os.environ.get("HM_ARCH_DB_PATH")
        if env_path:
            return env_path

        path = Path(self.db_path)
        if self.scope == IntegrationScope.GLOBAL:
            return str(path.expanduser())

        if path.is_absolute():
            return str(path)

        base = cwd if cwd is not None else Path.cwd()
        return str((base / path).resolve())

    def to_memory_config(self) -> MemoryConfig:
        """Build a :class:`~hm_arch.config.MemoryConfig` for :class:`~hm_arch.HMArch`."""
        if self.memory_preset is not None:
            config = MemoryConfig.preset(self.memory_preset)
        else:
            config = MemoryConfig()

        config.db_path = self.resolve_db_path()
        config.replay_sample_ratio = self.replay_sample_ratio
        config.enable_llm_providers = self.enable_llm_providers
        config.provider_fallback_to_local = self.provider_fallback_to_local
        config.auto_consolidate = False
        return config

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly mapping."""
        return {
            "db_path": self.db_path,
            "scope": self.scope.value,
            "recall_top_k": self.recall_top_k,
            "max_context_chars": self.max_context_chars,
            "consolidation_enabled": self.consolidation_enabled,
            "replay_sample_ratio": self.replay_sample_ratio,
            "memory_preset": self.memory_preset,
            "enable_llm_providers": self.enable_llm_providers,
            "provider_fallback_to_local": self.provider_fallback_to_local,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> IntegrationConfig:
        """Construct from a mapping (unknown keys are ignored)."""
        known = {field.name for field in fields(cls)}
        filtered = {key: value for key, value in data.items() if key in known}
        return cls(**filtered)
