"""Tests for agent integration configuration (MEM-39).

All tests run offline without external LLM/API keys.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest

from hm_arch import MemoryConfig
from hm_arch.integrations.config import IntegrationConfig, StorageScope


def _field_names(cls: type) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


REQUIRED_FIELDS = {
    "db_path",
    "scope",
    "recall_top_k",
    "max_context_chars",
    "auto_consolidate",
    "consolidate_on_idle",
    "replay_sample_ratio",
}


def test_required_fields_present() -> None:
    missing = REQUIRED_FIELDS - _field_names(IntegrationConfig)
    assert not missing, f"IntegrationConfig missing fields: {sorted(missing)}"


def test_defaults_are_offline_first() -> None:
    cfg = IntegrationConfig()
    assert cfg.scope is StorageScope.PROJECT
    assert cfg.recall_top_k == 5
    assert cfg.max_context_chars == 8000
    assert cfg.auto_consolidate is True
    assert cfg.consolidate_on_idle is True
    assert cfg.replay_sample_ratio == pytest.approx(1.0)
    assert cfg.resolve_db_path().endswith(".db")


def test_default_db_path_is_portable() -> None:
    cfg = IntegrationConfig()
    resolved = cfg.resolve_db_path()
    assert not resolved.startswith("/")
    assert Path(resolved).name.startswith(".")


def test_resolve_db_path_prefers_explicit_value() -> None:
    cfg = IntegrationConfig(db_path="./custom/memory.db")
    assert cfg.resolve_db_path() == "./custom/memory.db"


def test_resolve_db_path_uses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HM_ARCH_DB_PATH", "/tmp/hm_arch_integration.db")
    cfg = IntegrationConfig()
    assert cfg.resolve_db_path() == "/tmp/hm_arch_integration.db"


def test_resolve_db_path_explicit_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HM_ARCH_DB_PATH", "/tmp/env.db")
    cfg = IntegrationConfig(db_path="./explicit.db")
    assert cfg.resolve_db_path() == "./explicit.db"


def test_to_memory_config_preserves_offline_defaults() -> None:
    cfg = IntegrationConfig()
    memory_cfg = cfg.to_memory_config()
    assert isinstance(memory_cfg, MemoryConfig)
    assert memory_cfg.enable_llm_providers is False
    assert memory_cfg.llm_provider == "local"
    assert memory_cfg.embedding_provider == "local"
    assert memory_cfg.vector_backend == "local"
    assert memory_cfg.db_path == cfg.resolve_db_path()
    assert memory_cfg.replay_sample_ratio == cfg.replay_sample_ratio


def test_global_scope_uses_configured_db_path() -> None:
    cfg = IntegrationConfig(
        scope=StorageScope.GLOBAL,
        db_path="~/.hm-arch/global.db",
    )
    assert cfg.scope is StorageScope.GLOBAL
    assert cfg.resolve_db_path(os.path.expanduser) == os.path.expanduser(
        "~/.hm-arch/global.db"
    )


@pytest.mark.parametrize("bad_top_k", [0, -1])
def test_rejects_invalid_recall_top_k(bad_top_k: int) -> None:
    with pytest.raises(ValueError, match="recall_top_k"):
        IntegrationConfig(recall_top_k=bad_top_k)


@pytest.mark.parametrize("bad_size", [0, -100])
def test_rejects_invalid_max_context_chars(bad_size: int) -> None:
    with pytest.raises(ValueError, match="max_context_chars"):
        IntegrationConfig(max_context_chars=bad_size)
