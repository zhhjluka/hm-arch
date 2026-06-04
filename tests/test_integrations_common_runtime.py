"""Tests for packaged agent integration runtime (HM-40).

All tests run offline without external LLM/API keys.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from hm_arch import EventType, HMArch, MemoryConfig
from hm_arch.integrations.common import (
    build_turn_start_context,
    extract_agent_message,
    extract_task_from_payload,
    extract_user_message,
    open_memory,
    record_turn_end,
    resolve_db_path,
    run_idle_consolidation,
)


@pytest.fixture()
def hook_db_path() -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield str(Path(tmpdir) / "common_runtime.db")


def test_resolve_db_path_explicit_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HM_ARCH_DB_PATH", "/tmp/env.db")
    assert resolve_db_path("/tmp/explicit.db") == "/tmp/explicit.db"


def test_resolve_db_path_default_uses_cwd() -> None:
    path = resolve_db_path()
    assert path.endswith(".hm_arch_agent_memory.db")
    assert Path(path).parent == Path.cwd()


def test_payload_extractors_prefer_first_non_empty_field() -> None:
    payload = {
        "prompt": "  task text  ",
        "user_message": "user",
        "last_assistant_message": "agent",
    }
    assert extract_task_from_payload(payload) == "task text"
    assert extract_user_message(payload) == "user"
    assert extract_agent_message(payload) == "agent"


def test_payload_extractors_return_empty_for_missing_keys() -> None:
    assert extract_task_from_payload({}) == ""
    assert extract_user_message({}) == ""
    assert extract_agent_message({}) == ""


def test_build_turn_start_context_empty_task(hook_db_path: str) -> None:
    with open_memory(hook_db_path) as memory:
        assert build_turn_start_context(memory, "   ") == ""


def test_record_turn_end_skips_blank_messages(hook_db_path: str) -> None:
    with open_memory(hook_db_path) as memory:
        assert record_turn_end(memory, "  ", "  ") == []


def test_open_memory_and_consolidation_offline(hook_db_path: str) -> None:
    with open_memory(hook_db_path) as memory:
        memory.add("Seed memory", event_type=EventType.OBSERVATION)
        report = run_idle_consolidation(memory)
    assert report.extracted_semantics >= 0


def test_package_import_surface() -> None:
    import hm_arch.integrations.common as common

    for name in (
        "resolve_db_path",
        "open_memory",
        "build_turn_start_context",
        "record_turn_end",
        "run_idle_consolidation",
        "extract_task_from_payload",
        "extract_user_message",
        "extract_agent_message",
    ):
        assert hasattr(common, name)
