"""Route durable memory operations to global or project SQLite stores."""

from __future__ import annotations

from dataclasses import dataclass

from hm_arch import HMArch

from .common.paths import open_memory
from .config import IntegrationConfig, StorageScope


@dataclass
class MemoryStoreRouter:
    """Open HM-Arch stores according to integration storage scope.

    Writes use :attr:`~IntegrationConfig.scope` (project by default). Reads
    use the same active scope unless a caller overrides *scope* explicitly.
    """

    config: IntegrationConfig

    def resolve_path(self, scope: StorageScope | None = None) -> str:
        """Return the SQLite path for *scope* (defaults to ``config.scope``)."""
        return self.config.resolve_db_path(scope=scope)

    def open(self, scope: StorageScope | None = None) -> HMArch:
        """Open an :class:`~hm_arch.core.HMArch` instance for *scope*."""
        return open_memory(config=self.config, scope=scope)

    def open_for_write(self) -> HMArch:
        """Open the store that receives writes for the configured scope."""
        return self.open(scope=self.config.scope)
