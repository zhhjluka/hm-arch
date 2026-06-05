"""Tests for global/project memory store routing (MEM-54).

All tests run offline without external LLM/API keys.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hm_arch import HMArch, MemoryConfig
from hm_arch.integrations.common import open_memory, resolve_db_path
from hm_arch.integrations.config import IntegrationConfig, StorageScope
from hm_arch.integrations.storage_router import MemoryStoreRouter


@pytest.fixture
def store_paths(tmp_path: Path) -> tuple[str, str]:
    return str(tmp_path / "global.db"), str(tmp_path / "project.db")


def _dual_store_config(
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


def test_config_exposes_global_and_project_db_paths() -> None:
    cfg = IntegrationConfig(
        global_db_path="~/.hm-arch/global.db",
        project_db_path="./.hm-arch/memory.db",
    )
    assert cfg.global_db_path == "~/.hm-arch/global.db"
    assert cfg.project_db_path == "./.hm-arch/memory.db"


def test_default_scope_is_project() -> None:
    assert IntegrationConfig().scope is StorageScope.PROJECT


def test_resolve_project_db_path(store_paths: tuple[str, str]) -> None:
    global_db, project_db = store_paths
    cfg = _dual_store_config(global_db, project_db)
    assert cfg.resolve_db_path(scope=StorageScope.PROJECT) == project_db


def test_resolve_global_db_path(store_paths: tuple[str, str]) -> None:
    global_db, project_db = store_paths
    cfg = _dual_store_config(global_db, project_db)
    assert cfg.resolve_db_path(scope=StorageScope.GLOBAL) == global_db


def test_resolve_global_db_path_expands_user(store_paths: tuple[str, str]) -> None:
    global_db, project_db = store_paths
    cfg = IntegrationConfig(
        global_db_path="~/.hm-arch/global.db",
        project_db_path=project_db,
    )
    assert cfg.resolve_db_path(
        os.path.expanduser,
        scope=StorageScope.GLOBAL,
    ) == os.path.expanduser("~/.hm-arch/global.db")


def test_env_overrides_for_project_scope(
    monkeypatch: pytest.MonkeyPatch,
    store_paths: tuple[str, str],
) -> None:
    global_db, _ = store_paths
    monkeypatch.setenv("HM_ARCH_PROJECT_DB_PATH", "/tmp/project-only.db")
    cfg = IntegrationConfig(global_db_path=global_db)
    assert cfg.resolve_db_path(scope=StorageScope.PROJECT) == "/tmp/project-only.db"


def test_env_overrides_for_global_scope(
    monkeypatch: pytest.MonkeyPatch,
    store_paths: tuple[str, str],
) -> None:
    _, project_db = store_paths
    monkeypatch.setenv("HM_ARCH_GLOBAL_DB_PATH", "/tmp/global-only.db")
    cfg = IntegrationConfig(project_db_path=project_db)
    assert cfg.resolve_db_path(scope=StorageScope.GLOBAL) == "/tmp/global-only.db"


def test_legacy_db_path_overrides_scope_specific_paths(
    store_paths: tuple[str, str],
) -> None:
    global_db, project_db = store_paths
    legacy = "/tmp/legacy-single.db"
    cfg = IntegrationConfig(
        db_path=legacy,
        global_db_path=global_db,
        project_db_path=project_db,
    )
    assert cfg.resolve_db_path(scope=StorageScope.PROJECT) == legacy
    assert cfg.resolve_db_path(scope=StorageScope.GLOBAL) == legacy


def test_project_writes_do_not_enter_global_store(store_paths: tuple[str, str]) -> None:
    global_db, project_db = store_paths
    cfg = _dual_store_config(global_db, project_db, scope=StorageScope.PROJECT)
    router = MemoryStoreRouter(cfg)

    with router.open_for_write() as memory:
        memory.add("project-only repository fact")

    with HMArch(config=MemoryConfig(db_path=project_db)) as project_memory:
        project_hits = project_memory.search("repository fact")
        assert project_hits.results

    with HMArch(config=MemoryConfig(db_path=global_db)) as global_memory:
        assert global_memory.get_stats().by_layer[2] == 0
        global_hits = global_memory.search("repository fact")
        assert not global_hits.results


def test_global_writes_do_not_enter_project_store(store_paths: tuple[str, str]) -> None:
    global_db, project_db = store_paths
    cfg = _dual_store_config(global_db, project_db, scope=StorageScope.GLOBAL)
    router = MemoryStoreRouter(cfg)

    with router.open_for_write() as memory:
        memory.add("user-wide preference")

    with HMArch(config=MemoryConfig(db_path=global_db)) as global_memory:
        global_hits = global_memory.search("user-wide preference")
        assert global_hits.results

    with HMArch(config=MemoryConfig(db_path=project_db)) as project_memory:
        assert project_memory.get_stats().by_layer[2] == 0
        project_hits = project_memory.search("user-wide preference")
        assert not project_hits.results


def test_legacy_single_store_usage_remains_supported(tmp_path: Path) -> None:
    legacy_db = tmp_path / "legacy.db"
    cfg = IntegrationConfig(db_path=str(legacy_db))
    router = MemoryStoreRouter(cfg)

    with router.open_for_write() as memory:
        memory.add("legacy single-store note")

    with HMArch(config=MemoryConfig(db_path=str(legacy_db))) as memory:
        hits = memory.search("legacy single-store")
        assert hits.results


def test_open_memory_routes_by_config_scope(store_paths: tuple[str, str]) -> None:
    global_db, project_db = store_paths
    cfg = _dual_store_config(global_db, project_db, scope=StorageScope.PROJECT)

    with open_memory(config=cfg) as memory:
        memory.add("scoped via open_memory")

    with HMArch(config=MemoryConfig(db_path=project_db)) as project_memory:
        assert project_memory.search("scoped via open_memory").results
    with HMArch(config=MemoryConfig(db_path=global_db)) as global_memory:
        assert global_memory.get_stats().by_layer[2] == 0


def test_resolve_db_path_helper_uses_integration_config(
    store_paths: tuple[str, str],
) -> None:
    global_db, project_db = store_paths
    cfg = _dual_store_config(global_db, project_db)
    assert resolve_db_path(config=cfg, scope=StorageScope.GLOBAL) == global_db
    assert resolve_db_path(config=cfg, scope=StorageScope.PROJECT) == project_db
