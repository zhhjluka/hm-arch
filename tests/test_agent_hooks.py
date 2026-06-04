"""Tests for Codex and Claude Code agent hook examples (MEM-23).

All tests run offline without external LLM/API keys.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from hm_arch.integrations.common import (
    build_turn_start_context,
    open_memory,
    record_turn_end,
    run_idle_consolidation,
)
from examples.claude_code_hooks.hooks import (
    claude_idle_consolidation_hook,
    claude_turn_end_hook,
    claude_turn_start_hook,
)
from examples.codex_hooks.hooks import (
    codex_idle_consolidation_hook,
    codex_turn_end_hook,
    codex_turn_start_hook,
)
from hm_arch import EventType, HMArch, MemoryConfig

_REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def hook_db_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield str(Path(tmpdir) / "hooks_test.db")


@pytest.fixture()
def seeded_memory(hook_db_path: str) -> HMArch:
    config = MemoryConfig(db_path=hook_db_path, replay_sample_ratio=1.0)
    memory = HMArch(config=config)
    memory.add(
        "Repository uses uv and pytest for offline verification",
        event_type=EventType.OBSERVATION,
        importance=0.85,
    )
    memory.add(
        "User prefers portable hook examples without home-directory paths",
        event_type=EventType.CONVERSATION,
        importance=0.9,
    )
    yield memory
    memory.close()


def test_turn_start_returns_context_for_task(seeded_memory: HMArch) -> None:
    context = build_turn_start_context(
        seeded_memory,
        "How do we run offline tests?",
    )
    assert context
    assert "pytest" in context.lower() or "offline" in context.lower()


@pytest.mark.parametrize(
    "turn_start_hook",
    [codex_turn_start_hook, claude_turn_start_hook],
)
def test_agent_turn_start_hooks(
    hook_db_path: str,
    turn_start_hook,
) -> None:
    config = MemoryConfig(db_path=hook_db_path, replay_sample_ratio=1.0)
    with HMArch(config=config) as memory:
        memory.add("Agent hooks must stay offline", event_type=EventType.TASK)

    context = turn_start_hook(
        {"prompt": "offline agent hooks"},
        db_path=hook_db_path,
    )
    assert "offline" in context.lower()


@pytest.mark.parametrize(
    "turn_end_hook",
    [codex_turn_end_hook, claude_turn_end_hook],
)
def test_agent_turn_end_records_messages(
    hook_db_path: str,
    turn_end_hook,
) -> None:
    config = MemoryConfig(db_path=hook_db_path, replay_sample_ratio=1.0)
    with HMArch(config=config) as memory:
        before = memory.get_stats().by_layer[2]

    ids = turn_end_hook(
        {
            "prompt": "Record this turn",
            "last_assistant_message": "Turn stored in episodic memory.",
        },
        db_path=hook_db_path,
    )
    assert len(ids) == 2

    with HMArch(config=config) as memory:
        after = memory.get_stats().by_layer[2]
        assert after == before + 2
        hits = memory.search("episodic memory", top_k=3)
        assert hits.results


@pytest.mark.parametrize(
    "idle_hook",
    [codex_idle_consolidation_hook, claude_idle_consolidation_hook],
)
def test_agent_idle_consolidation_does_not_crash(
    hook_db_path: str,
    idle_hook,
) -> None:
    summary = idle_hook({}, db_path=hook_db_path)
    assert "extracted_semantics" in summary

    config = MemoryConfig(db_path=hook_db_path, replay_sample_ratio=1.0)
    with HMArch(config=config) as memory:
        stats = memory.get_stats()
        assert stats.last_consolidation_at is not None


def test_record_turn_end_common_api(seeded_memory: HMArch) -> None:
    before = seeded_memory.get_stats().by_layer[2]
    ids = record_turn_end(
        seeded_memory,
        "What testing stack do we use?",
        "uv run pytest.",
    )
    assert len(ids) == 2
    assert seeded_memory.get_stats().by_layer[2] == before + 2


def test_run_idle_consolidation_on_empty_db(hook_db_path: str) -> None:
    with open_memory(hook_db_path) as memory:
        report = run_idle_consolidation(memory)
    assert report.extracted_semantics >= 0


def test_resolve_db_path_uses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HM_ARCH_DB_PATH", "/tmp/hm_arch_test_only.db")
    from hm_arch.integrations.common import resolve_db_path

    assert resolve_db_path() == "/tmp/hm_arch_test_only.db"


def test_codex_turn_start_script_emits_json(hook_db_path: str, monkeypatch) -> None:
    monkeypatch.setenv("HM_ARCH_DB_PATH", hook_db_path)
    config = MemoryConfig(db_path=hook_db_path, replay_sample_ratio=1.0)
    with HMArch(config=config) as memory:
        memory.add("Scripted hook context seed", event_type=EventType.OBSERVATION)

    payload = json.dumps({"prompt": "hook context seed"})
    proc = subprocess.run(
        [sys.executable, "examples/codex_hooks/turn_start.py"],
        input=payload,
        text=True,
        capture_output=True,
        check=True,
        cwd=_REPO_ROOT,
    )
    out = json.loads(proc.stdout)
    assert "hookSpecificOutput" in out
    assert "Scripted" in out["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize(
    "demo_script",
    [
        "examples/codex_hooks/demo.py",
        "examples/claude_code_hooks/demo.py",
    ],
)
def test_demo_scripts_run(demo_script: str) -> None:
    subprocess.run(
        [sys.executable, demo_script],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
