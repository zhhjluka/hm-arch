"""Merge and filter search results across global and project memory stores (MEM-55)."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, replace
from pathlib import Path

from hm_arch.forgetting.strength import content_hash
from hm_arch.types import MemoryItem, MemoryProvenance, SearchResult

from .common.paths import open_memory
from .config import IntegrationConfig, StorageScope

_STORAGE_SCOPE_META = "hm_arch_storage_scope"


@dataclass(frozen=True)
class MemorySearchFilters:
    """Optional provenance filters applied after cross-store retrieval."""

    agent: str | None = None
    project: str | None = None
    session: str | None = None
    memory_type: str | None = None

    def is_empty(self) -> bool:
        return (
            self.agent is None
            and self.project is None
            and self.session is None
            and self.memory_type is None
        )


def dual_store_enabled(config: IntegrationConfig) -> bool:
    """Return whether *config* uses separate global and project SQLite files."""
    if config.db_path:
        return False
    global_path = config.resolve_db_path(scope=StorageScope.GLOBAL)
    project_path = config.resolve_db_path(scope=StorageScope.PROJECT)
    return global_path != project_path


def resolve_project_context(explicit: str | None = None) -> str:
    """Return the active project identifier used for isolation checks."""
    if explicit is not None and explicit.strip():
        return _normalize_project_id(explicit)
    env_value = os.environ.get("HM_ARCH_PROJECT")
    if env_value and env_value.strip():
        return _normalize_project_id(env_value)
    return str(Path.cwd().resolve())


def search_cross_stores(
    config: IntegrationConfig,
    query: str,
    top_k: int = 10,
    *,
    filters: MemorySearchFilters | None = None,
    project_context: str | None = None,
    min_retention: float = 0.1,
    layer_filter: list[int] | None = None,
) -> SearchResult:
    """Search global and project stores, then merge, rank, and deduplicate hits.

  When :func:`dual_store_enabled` is false, this delegates to a single-store
  :meth:`~hm_arch.core.HMArch.search` on the configured scope.
    """
    if top_k < 1:
        raise ValueError("top_k must be >= 1")

    active_filters = filters or MemorySearchFilters()
    context = resolve_project_context(project_context)

    if not dual_store_enabled(config):
        with open_memory(config=config) as memory:
            result = memory.search(
                query,
                top_k=top_k,
                min_retention=min_retention,
                layer_filter=layer_filter,
            )
        kept = _post_filter_results(
            result.results,
            filters=active_filters,
            project_context=context,
            storage_scope=config.scope,
        )
        ranked = sorted(kept, key=lambda hit: -hit.score)[:top_k]
        return replace(result, results=ranked)

    per_store_k = max(top_k, top_k * 2)
    pooled: list[tuple[MemoryItem, StorageScope]] = []
    source_breakdown: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    total_scanned = 0

    t0 = time.monotonic()
    for scope in (StorageScope.GLOBAL, StorageScope.PROJECT):
        with open_memory(config=config, scope=scope) as memory:
            partial = memory.search(
                query,
                top_k=per_store_k,
                min_retention=min_retention,
                layer_filter=layer_filter,
            )
        total_scanned += partial.total_scanned
        for layer, count in partial.source_breakdown.items():
            source_breakdown[layer] = source_breakdown.get(layer, 0) + count
        for item in partial.results:
            pooled.append((item, scope))

    kept = [
        (item, scope)
        for item, scope in pooled
        if _passes_provenance_and_isolation(
            item,
            filters=active_filters,
            storage_scope=scope,
            project_context=context,
        )
    ]
    merged = _merge_rank_deduplicate(kept, top_k=top_k)
    elapsed_ms = (time.monotonic() - t0) * 1000

    return SearchResult(
        results=merged,
        total_scanned=total_scanned,
        timing_ms=elapsed_ms,
        source_breakdown=source_breakdown,
    )


def _post_filter_results(
    items: list[MemoryItem],
    *,
    filters: MemorySearchFilters,
    project_context: str,
    storage_scope: StorageScope,
) -> list[MemoryItem]:
    return [
        _tag_storage_scope(item, storage_scope)
        for item in items
        if _passes_provenance_and_isolation(
            item,
            filters=filters,
            storage_scope=storage_scope,
            project_context=project_context,
        )
    ]


def _passes_provenance_and_isolation(
    item: MemoryItem,
    *,
    filters: MemorySearchFilters,
    storage_scope: StorageScope,
    project_context: str,
) -> bool:
    if not _matches_provenance_filters(item.provenance, filters):
        return False
    return _passes_project_isolation(
        item,
        storage_scope=storage_scope,
        project_context=project_context,
    )


def _matches_provenance_filters(
    provenance: MemoryProvenance | None,
    filters: MemorySearchFilters,
) -> bool:
    if filters.is_empty():
        return True
    if provenance is None:
        return False
    if filters.agent is not None and provenance.agent != filters.agent:
        return False
    if filters.project is not None and provenance.project != filters.project:
        return False
    if filters.session is not None and provenance.session != filters.session:
        return False
    if filters.memory_type is not None and provenance.memory_type != filters.memory_type:
        return False
    return True


def _passes_project_isolation(
    item: MemoryItem,
    *,
    storage_scope: StorageScope,
    project_context: str,
) -> bool:
    provenance = item.provenance
    if provenance is None or provenance.project is None:
        return True
    tagged = _normalize_project_id(provenance.project)
    current = _normalize_project_id(project_context)
    if storage_scope is StorageScope.GLOBAL:
        return tagged == current
    return tagged == current


def _merge_rank_deduplicate(
    items: list[tuple[MemoryItem, StorageScope]],
    *,
    top_k: int,
) -> list[MemoryItem]:
    best: dict[tuple[int, str], MemoryItem] = {}
    for item, scope in items:
        tagged = _tag_storage_scope(item, scope)
        key = (tagged.layer, content_hash(tagged.content))
        existing = best.get(key)
        if existing is None or tagged.score > existing.score:
            best[key] = tagged
    ranked = sorted(best.values(), key=lambda hit: -hit.score)
    return ranked[:top_k]


def _tag_storage_scope(item: MemoryItem, scope: StorageScope) -> MemoryItem:
    metadata = dict(item.metadata)
    metadata[_STORAGE_SCOPE_META] = scope.value
    return replace(item, metadata=metadata)


def _normalize_project_id(value: str) -> str:
    text = value.strip()
    try:
        return str(Path(text).resolve())
    except (OSError, RuntimeError):
        return text
