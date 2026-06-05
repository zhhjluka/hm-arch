"""Cross-store memory search merge, filter, and isolation tests (MEM-55)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hm_arch import EventType, HMArch, MemoryConfig
from hm_arch.integrations.config import IntegrationConfig, StorageScope
from hm_arch.integrations.cross_store_search import (
    MemorySearchFilters,
    dual_store_enabled,
    resolve_project_context,
    search_cross_stores,
)
from hm_arch.integrations.storage_router import MemoryStoreRouter


@pytest.fixture
def store_paths(tmp_path: Path) -> tuple[str, str]:
    return str(tmp_path / "global.db"), str(tmp_path / "project.db")


def _dual_config(
    global_db: str,
    project_db: str,
    *,
    scope: StorageScope = StorageScope.PROJECT,
) -> IntegrationConfig:
    return IntegrationConfig(
        scope=scope,
        global_db_path=global_db,
        project_db_path=project_db,
    )


def test_dual_store_enabled_requires_distinct_paths(store_paths: tuple[str, str]) -> None:
    global_db, project_db = store_paths
    assert dual_store_enabled(_dual_config(global_db, project_db)) is True
    legacy = IntegrationConfig(db_path=global_db)
    assert dual_store_enabled(legacy) is False


def test_global_preference_recallable_from_project_context(
    store_paths: tuple[str, str],
) -> None:
    global_db, project_db = store_paths
    cfg = _dual_config(global_db, project_db)

    with HMArch(config=MemoryConfig(db_path=global_db)) as global_memory:
        global_memory.add(
            "User prefers dark mode in all editors",
            agent="codex",
            project=None,
        )

    with HMArch(config=MemoryConfig(db_path=project_db)) as project_memory:
        project_memory.add(
            "This repo uses pytest for testing",
            agent="claude-code",
            project="/workspace/app",
        )

    result = search_cross_stores(
        cfg,
        "dark mode editors",
        top_k=5,
        project_context="/workspace/app",
        min_retention=0.0,
    )
    contents = {item.content for item in result.results}
    assert any("dark mode" in text for text in contents)
    global_hit = next(item for item in result.results if "dark mode" in item.content)
    assert global_hit.metadata.get("hm_arch_storage_scope") == "global"
    assert global_hit.provenance is not None
    assert global_hit.provenance.agent == "codex"


def test_project_private_memory_not_leaked_to_unrelated_project(
    store_paths: tuple[str, str],
) -> None:
    global_db, project_db = store_paths
    cfg = _dual_config(global_db, project_db)

    with HMArch(config=MemoryConfig(db_path=project_db)) as project_memory:
        project_memory.add(
            "Secret deploy key lives in vault subdirectory",
            agent="cursor",
            project="/workspace/project-alpha",
        )

    result = search_cross_stores(
        cfg,
        "deploy key vault",
        top_k=5,
        project_context="/workspace/project-beta",
        min_retention=0.0,
    )
    assert not any("deploy key" in item.content for item in result.results)


def test_project_private_memory_visible_in_matching_project(
    store_paths: tuple[str, str],
) -> None:
    global_db, project_db = store_paths
    cfg = _dual_config(global_db, project_db)

    with HMArch(config=MemoryConfig(db_path=project_db)) as project_memory:
        project_memory.add(
            "CI runs on every pull request",
            agent="cursor",
            project="/workspace/project-alpha",
        )

    result = search_cross_stores(
        cfg,
        "pull request CI",
        top_k=5,
        project_context="/workspace/project-alpha",
        min_retention=0.0,
    )
    assert any("pull request" in item.content for item in result.results)
    hit = next(item for item in result.results if "pull request" in item.content)
    assert hit.metadata.get("hm_arch_storage_scope") == "project"


def test_merge_deduplicates_same_content_across_stores(
    store_paths: tuple[str, str],
) -> None:
    global_db, project_db = store_paths
    cfg = _dual_config(global_db, project_db)
    shared = "Always format Python with black before commit"

    with HMArch(config=MemoryConfig(db_path=global_db)) as global_memory:
        global_memory.add(shared, agent="codex")
    with HMArch(config=MemoryConfig(db_path=project_db)) as project_memory:
        project_memory.add(shared, agent="claude-code", project="/workspace/app")

    result = search_cross_stores(
        cfg,
        "format Python black",
        top_k=5,
        project_context="/workspace/app",
        min_retention=0.0,
    )
    matching = [item for item in result.results if "format Python" in item.content]
    assert len(matching) == 1


def test_provenance_filters_by_agent(store_paths: tuple[str, str]) -> None:
    global_db, project_db = store_paths
    cfg = _dual_config(global_db, project_db)

    with HMArch(config=MemoryConfig(db_path=global_db)) as global_memory:
        global_memory.add("Codex-only toolchain preference", agent="codex")
        global_memory.add("Claude-only review preference", agent="claude-code")

    result = search_cross_stores(
        cfg,
        "preference",
        top_k=10,
        filters=MemorySearchFilters(agent="codex"),
        min_retention=0.0,
    )
    assert result.results
    assert all(item.provenance and item.provenance.agent == "codex" for item in result.results)


def test_provenance_filters_by_memory_type(store_paths: tuple[str, str]) -> None:
    global_db, project_db = store_paths
    cfg = _dual_config(global_db, project_db)

    with HMArch(config=MemoryConfig(db_path=project_db)) as project_memory:
        project_memory.add(
            "Chose PostgreSQL",
            event_type=EventType.DECISION,
            agent="cursor",
            project="/workspace/app",
        )
        project_memory.add(
            "Saw a failing migration",
            event_type=EventType.OBSERVATION,
            agent="cursor",
            project="/workspace/app",
        )

    result = search_cross_stores(
        cfg,
        "PostgreSQL migration",
        top_k=10,
        filters=MemorySearchFilters(memory_type="decision"),
        project_context="/workspace/app",
        min_retention=0.0,
    )
    assert len(result.results) == 1
    assert result.results[0].provenance is not None
    assert result.results[0].provenance.memory_type == "decision"


def test_memory_store_router_search_uses_cross_store(store_paths: tuple[str, str]) -> None:
    global_db, project_db = store_paths
    cfg = _dual_config(global_db, project_db)

    with HMArch(config=MemoryConfig(db_path=global_db)) as global_memory:
        global_memory.add("Shared lint rule: max line length 100", agent="codex")

    router = MemoryStoreRouter(cfg)
    hits = router.search("lint rule", top_k=3, min_retention=0.0)
    assert hits.results
    assert hits.results[0].metadata.get("hm_arch_storage_scope") == "global"


def test_resolve_project_context_prefers_explicit_value(tmp_path: Path) -> None:
    assert resolve_project_context("/tmp/custom-project") == str(
        Path("/tmp/custom-project").resolve()
    )


def test_cross_agent_global_recall(store_paths: tuple[str, str]) -> None:
    """Global preference recorded by one agent is visible to another via search."""
    global_db, project_db = store_paths
    cfg = _dual_config(global_db, project_db)

    with HMArch(config=MemoryConfig(db_path=global_db)) as global_memory:
        global_memory.add(
            "User wants concise commit messages",
            agent="codex",
        )

    codex_view = search_cross_stores(
        cfg,
        "concise commit",
        top_k=3,
        filters=MemorySearchFilters(agent="codex"),
        min_retention=0.0,
    )
    claude_view = search_cross_stores(
        cfg,
        "concise commit",
        top_k=3,
        min_retention=0.0,
    )
    assert codex_view.results
    assert claude_view.results
    assert any("commit messages" in item.content for item in claude_view.results)
