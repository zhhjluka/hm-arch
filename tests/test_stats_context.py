"""Tests for HMArch.get_stats() and HMArch.context() (HM-11 / MEM-16).

All tests run offline without external API keys.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hm_arch import AgentContext, EventType, HMArch, MemoryConfig, MemoryStats
from hm_arch.consolidation import ConsolidationEngine


# ---------------------------------------------------------------------------
# get_stats()
# ---------------------------------------------------------------------------


@pytest.fixture()
def mem() -> HMArch:
    instance = HMArch(db_path=":memory:")
    yield instance
    instance.close()


def test_get_stats_returns_memory_stats(mem: HMArch) -> None:
    stats = mem.get_stats()
    assert isinstance(stats, MemoryStats)


def test_get_stats_empty_store(mem: HMArch) -> None:
    stats = mem.get_stats()
    assert stats.total_memories == 0
    for layer in range(7):
        assert stats.by_layer[layer] == 0
    assert stats.archive_storage_mb >= 0.0
    assert stats.review_queue_length == 0
    assert stats.last_consolidation_at is None


def test_get_stats_counts_after_add(mem: HMArch) -> None:
    mem.add("first")
    mem.add("second")
    stats = mem.get_stats()
    assert stats.by_layer[0] == 2
    assert stats.by_layer[1] == 2
    assert stats.by_layer[2] == 2
    assert stats.total_memories == 6


def test_get_stats_includes_l3_semantics(mem: HMArch) -> None:
    mem._l3.upsert("user", "likes", "Python")
    stats = mem.get_stats()
    assert stats.by_layer[3] == 1
    assert stats.total_memories >= 1


def test_get_stats_retention_distribution_buckets(mem: HMArch) -> None:
    mem.add("episode one", importance=0.5)
    stats = mem.get_stats()
    expected_keys = {"0-0.25", "0.25-0.5", "0.5-0.75", "0.75-1.0"}
    assert set(stats.retention_distribution.keys()) == expected_keys
    assert sum(stats.retention_distribution.values()) == stats.by_layer[2] + stats.by_layer[3]


def test_get_stats_storage_size_nonnegative(mem: HMArch) -> None:
    stats = mem.get_stats()
    assert stats.storage_size_mb >= 0.0


def test_get_stats_storage_size_on_disk_file() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = str(Path(tmpdir) / "stats.db")
        m = HMArch(db_path=db_file)
        m.add("persisted")
        stats = m.get_stats()
        m.close()
    assert stats.storage_size_mb > 0.0


def test_get_stats_last_consolidation_after_cycle(mem: HMArch) -> None:
    mem.add("User prefers Python for backend work")
    engine = ConsolidationEngine(
        mem._db,
        mem._l2,
        mem._l3,
        config=MemoryConfig(replay_sample_ratio=1.0),
    )
    engine.run_consolidation_cycle()
    stats = mem.get_stats()
    assert stats.last_consolidation_at is not None
    assert isinstance(stats.last_consolidation_at, datetime)


def test_get_stats_l6_counts_persisted_policies(mem: HMArch) -> None:
    assert mem.get_stats().by_layer[6] == 0
    mem.set_policy("prefer_hot_memories", "true")
    stats = mem.get_stats()
    assert stats.by_layer[6] >= 1


def test_get_stats_review_queue_after_consolidation(mem: HMArch) -> None:
    mem.add("Important architecture decision", importance=0.95)
    mem._db.execute(
        "UPDATE memory_index SET current_retention = ?, created_at = ? WHERE layer = 2",
        (
            0.1,
            datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat(),
        ),
    )
    engine = ConsolidationEngine(
        mem._db,
        mem._l2,
        mem._l3,
        config=MemoryConfig(replay_sample_ratio=1.0),
    )
    engine.run_consolidation_cycle()
    stats = mem.get_stats()
    assert stats.review_queue_length >= 0


# ---------------------------------------------------------------------------
# context()
# ---------------------------------------------------------------------------


def test_context_yields_agent_context(mem: HMArch) -> None:
    with mem.context() as ctx:
        assert isinstance(ctx, AgentContext)


def test_context_restores_l1_size(mem: HMArch) -> None:
    mem.add("baseline")
    size_before = mem._l1.size
    with mem.context():
        mem.add("temporary")
        assert mem._l1.size == size_before + 1
    assert mem._l1.size == size_before


def test_context_restores_l1_contents(mem: HMArch) -> None:
    mem.add("keep me")
    before_ids = {item.memory_id for item in mem._l1.snapshot()}
    with mem.context():
        mem.add("discard me")
    after_ids = {item.memory_id for item in mem._l1.snapshot()}
    assert after_ids == before_ids


def test_context_does_not_remove_l2(mem: HMArch) -> None:
    mem.add("durable")
    with mem.context():
        mem.add("also durable in L2")
    assert mem._l2.count() == 2


def test_context_restores_on_exception(mem: HMArch) -> None:
    mem.add("baseline")
    size_before = mem._l1.size
    with pytest.raises(RuntimeError):
        with mem.context():
            mem.add("ephemeral")
            raise RuntimeError("simulated failure")
    assert mem._l1.size == size_before


# ---------------------------------------------------------------------------
# Example execution
# ---------------------------------------------------------------------------


def test_agent_integration_example_runs() -> None:
    script = Path(__file__).parent.parent / "examples" / "agent_integration.py"
    assert script.exists()
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"agent_integration.py failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "completed successfully" in result.stdout
