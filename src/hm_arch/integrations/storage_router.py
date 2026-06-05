"""Route durable memory operations to global or project SQLite stores."""

from __future__ import annotations

from dataclasses import dataclass

from hm_arch import HMArch
from hm_arch.types import SearchResult

from .common.paths import open_memory
from .config import IntegrationConfig, StorageScope
from .cross_store_search import MemorySearchFilters, search_cross_stores


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

    def search(
        self,
        query: str,
        top_k: int | None = None,
        *,
        filters: MemorySearchFilters | None = None,
        project_context: str | None = None,
        min_retention: float = 0.1,
        layer_filter: list[int] | None = None,
    ) -> SearchResult:
        """Search configured stores with merge, rank, dedupe, and isolation."""
        effective_top_k = top_k if top_k is not None else self.config.recall_top_k
        return search_cross_stores(
            self.config,
            query,
            effective_top_k,
            filters=filters,
            project_context=project_context,
            min_retention=min_retention,
            layer_filter=layer_filter,
        )
