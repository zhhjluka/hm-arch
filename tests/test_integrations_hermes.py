"""Offline tests for the Hermes Agent Memory Provider lifecycle adapter (MEM-46)."""

from __future__ import annotations

import json
import tempfile
import threading
import time
from pathlib import Path

import pytest

from hm_arch import EventType, HMArch, MemoryConfig
from hm_arch.integrations.config import IntegrationConfig
from hm_arch.integrations.hermes import (
    HM_ARCH_PROVIDER_NAME,
    ExternalProviderConflict,
    HMArchHermesMemoryProvider,
    assert_registration_allowed,
    detect_external_provider_conflict,
    merge_plugin_settings,
    read_memory_provider,
    register,
    resolve_db_path,
)


class _RecordingContext:
    def __init__(self, *, hermes_home: str | None = None) -> None:
        self.hermes_home = hermes_home
        self.providers: list[HMArchHermesMemoryProvider] = []

    def register_memory_provider(self, provider: HMArchHermesMemoryProvider) -> None:
        self.providers.append(provider)


@pytest.fixture()
def hermes_home() -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture()
def provider_db(hermes_home: str) -> tuple[HMArchHermesMemoryProvider, str]:
    db_path = str(Path(hermes_home) / "lifecycle.db")
    provider = HMArchHermesMemoryProvider(
        IntegrationConfig(db_path=db_path, recall_top_k=3),
    )
    yield provider, db_path
    provider.shutdown()


def test_read_memory_provider_nested_and_flat_keys() -> None:
    assert read_memory_provider({"memory": {"provider": "mem0"}}) == "mem0"
    assert read_memory_provider({"memory.provider": "hm-arch"}) == "hm-arch"
    assert read_memory_provider({}) is None


def test_detect_external_provider_conflict_blocks_other_providers() -> None:
    conflict = detect_external_provider_conflict({"memory": {"provider": "mem0"}})
    assert conflict is not None
    assert conflict.configured_provider == "mem0"
    assert conflict.requested_provider == HM_ARCH_PROVIDER_NAME


def test_detect_external_provider_conflict_allows_hm_arch() -> None:
    assert (
        detect_external_provider_conflict({"memory": {"provider": "hm-arch"}})
        is None
    )


def test_assert_registration_allowed_raises_for_conflicts() -> None:
    with pytest.raises(ExternalProviderConflict):
        assert_registration_allowed({"memory": {"provider": "honcho"}})


def test_merge_plugin_settings_does_not_overwrite_external_provider() -> None:
    config = {"memory": {"provider": "mem0"}, "plugins": {}}
    merged = merge_plugin_settings(config, {"db_path": "/tmp/test.db"})
    assert read_memory_provider(merged) == "mem0"
    assert merged["plugins"]["hm-arch"]["db_path"] == "/tmp/test.db"


def test_merge_plugin_settings_sets_provider_when_empty() -> None:
    merged = merge_plugin_settings({}, {"db_path": "/tmp/hm.db"})
    assert read_memory_provider(merged) == HM_ARCH_PROVIDER_NAME


def test_resolve_db_path_defaults_under_hermes_home(hermes_home: str) -> None:
    path = resolve_db_path(hermes_home)
    assert path.endswith("hm_arch_memory.db")
    assert Path(path).parent == Path(hermes_home)


def test_register_refuses_conflicting_provider(hermes_home: str) -> None:
    config_path = Path(hermes_home) / "config.yaml"
    config_path.write_text(
        "memory:\n  provider: mem0\n",
        encoding="utf-8",
    )
    ctx = _RecordingContext(hermes_home=hermes_home)
    with pytest.raises(ExternalProviderConflict):
        register(ctx)
    assert ctx.providers == []


def test_register_adds_provider_when_allowed(hermes_home: str) -> None:
    ctx = _RecordingContext(hermes_home=hermes_home)
    register(ctx)
    assert len(ctx.providers) == 1
    assert ctx.providers[0].name == HM_ARCH_PROVIDER_NAME


def test_lifecycle_recall_record_compress_consolidate_shutdown(
    provider_db: tuple[HMArchHermesMemoryProvider, str],
) -> None:
    provider, db_path = provider_db
    provider.initialize("session-1", hermes_home=str(Path(db_path).parent))

    remember = json.loads(
        provider.handle_tool_call(
            "hm_arch_remember",
            {"content": "User prefers pytest for offline verification"},
        )
    )
    assert remember["memory_id"]

    context = provider.prefetch("How do we run offline tests?")
    assert "pytest" in context.lower()

    provider.sync_turn("What test runner?", "We use pytest.", session_id="session-1")
    time.sleep(0.2)

    summary = provider.on_pre_compress(
        [
            {"role": "user", "content": "Capture this before compression"},
            {"role": "assistant", "content": "Stored for HM-Arch."},
        ]
    )
    assert "compression" in summary.lower()

    provider.on_session_end([])
    provider.shutdown()

    reopened = HMArch(config=MemoryConfig(db_path=db_path))
    try:
        hits = reopened.search("pytest offline", top_k=5)
        assert hits.results
    finally:
        reopened.close()


def test_queue_prefetch_populates_next_turn(
    provider_db: tuple[HMArchHermesMemoryProvider, str],
) -> None:
    provider, db_path = provider_db
    provider.initialize("session-2", hermes_home=str(Path(db_path).parent))
    provider.handle_tool_call(
        "hm_arch_remember",
        {"content": "Repository uses uv for package management"},
    )
    provider.queue_prefetch("package manager")
    deadline = time.time() + 2.0
    context = ""
    while time.time() < deadline:
        context = provider.prefetch("package manager")
        if context.strip():
            break
        time.sleep(0.05)
    assert "uv" in context.lower()
    provider.shutdown()


def test_sync_turn_skips_non_primary_context(
    provider_db: tuple[HMArchHermesMemoryProvider, str],
) -> None:
    provider, db_path = provider_db
    provider.initialize(
        "session-3",
        hermes_home=str(Path(db_path).parent),
        agent_context="cron",
    )
    provider.sync_turn("cron prompt", "cron response")
    time.sleep(0.2)
    provider.shutdown()

    reopened = HMArch(config=MemoryConfig(db_path=db_path))
    try:
        hits = reopened.search("cron prompt", top_k=3)
        assert hits.results == []
    finally:
        reopened.close()


def test_on_memory_write_mirrors_builtin_entries(
    provider_db: tuple[HMArchHermesMemoryProvider, str],
) -> None:
    provider, db_path = provider_db
    provider.initialize("session-4", hermes_home=str(Path(db_path).parent))
    provider.on_memory_write("add", "user", "Always run tests offline")
    provider.shutdown()

    reopened = HMArch(config=MemoryConfig(db_path=db_path))
    try:
        hits = reopened.search("offline tests", top_k=3)
        assert hits.results
    finally:
        reopened.close()


def test_provider_tools_search_and_remember(
    provider_db: tuple[HMArchHermesMemoryProvider, str],
) -> None:
    provider, _db_path = provider_db
    provider.initialize("session-5")
    schemas = {schema["name"] for schema in provider.get_tool_schemas()}
    assert schemas == {"hm_arch_search", "hm_arch_remember"}

    stored = json.loads(
        provider.handle_tool_call(
            "hm_arch_remember",
            {"content": "Uses SQLite as the source of truth"},
        )
    )
    searched = json.loads(
        provider.handle_tool_call(
            "hm_arch_search",
            {"query": "source of truth", "top_k": 2},
        )
    )
    assert stored["memory_id"]
    assert searched["count"] >= 1
    provider.shutdown()


def test_is_available_without_network() -> None:
    provider = HMArchHermesMemoryProvider()
    assert provider.is_available() is True


def test_initialize_creates_missing_db_parent_directories() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "missing" / "nested" / "memory.db"
        assert not db_path.parent.exists()

        provider = HMArchHermesMemoryProvider(
            IntegrationConfig(db_path=str(db_path)),
        )
        try:
            provider.initialize("session-nested-db")
            assert db_path.parent.is_dir()
            assert provider._memory is not None

            stored = json.loads(
                provider.handle_tool_call(
                    "hm_arch_remember",
                    {"content": "Nested db path works"},
                )
            )
            assert stored["memory_id"]
        finally:
            provider.shutdown()


def test_sync_turn_is_non_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = HMArchHermesMemoryProvider(IntegrationConfig(db_path=":memory:"))
    provider.initialize("session-6")
    started = threading.Event()
    release = threading.Event()

    from hm_arch.integrations.common import record as record_module

    original_record = record_module.record_turn_end

    def slow_record(*args: object, **kwargs: object) -> list[str]:
        release.wait(timeout=1.0)
        started.set()
        return original_record(*args, **kwargs)

    monkeypatch.setattr(
        "hm_arch.integrations.hermes.provider.record_turn_end",
        slow_record,
    )
    provider.sync_turn("hello", "world")
    assert not started.is_set()
    release.set()
    deadline = time.time() + 1.0
    while time.time() < deadline and not started.is_set():
        time.sleep(0.01)
    assert started.is_set()
    provider.shutdown()
