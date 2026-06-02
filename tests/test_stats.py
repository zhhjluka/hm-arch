"""Tests for HMArch.get_stats() (HM-11)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from hm_arch import HMArch, MemoryStats
from hm_arch.types import EventType


@pytest.fixture()
def mem() -> HMArch:
    instance = HMArch(db_path=":memory:")
    yield instance
    instance.close()


def test_get_stats_returns_memory_stats(mem: HMArch) -> None:
    stats = mem.get_stats()
    assert isinstance(stats, MemoryStats)


def test_get_stats_empty_memory(mem: HMArch) -> None:
    stats = mem.get_stats()
    assert stats.total_memories == 0
    assert stats.by_layer[1] == 0
    assert stats.by_layer[2] == 0
    assert stats.by_layer[3] == 0
    assert stats.review_queue_length == 0
    assert stats.last_consolidation_at is None
    assert stats.storage_size_mb >= 0.0


def test_get_stats_by_layer_counts(mem: HMArch) -> None:
    mem.add("first", event_type=EventType.OBSERVATION)
    mem.add("second", event_type=EventType.CONVERSATION)
    stats = mem.get_stats()
    # Each add() writes L1 + L2
    assert stats.by_layer[1] == 2
    assert stats.by_layer[2] == 2
    assert stats.total_memories == stats.by_layer[1] + stats.by_layer[2] + stats.by_layer[3]


def test_get_stats_retention_distribution_keys(mem: HMArch) -> None:
    mem.add("fresh memory")
    stats = mem.get_stats()
    assert set(stats.retention_distribution.keys()) == {
        "0-0.25",
        "0.25-0.5",
        "0.5-0.75",
        "0.75-1.0",
    }
    assert sum(stats.retention_distribution.values()) == stats.by_layer[2] + stats.by_layer[3]


def test_get_stats_storage_size_nonnegative(mem: HMArch) -> None:
    mem.add("content for storage")
    stats = mem.get_stats()
    assert stats.storage_size_mb >= 0.0


def test_get_stats_file_db_reports_size(tmp_path) -> None:
    db_file = str(tmp_path / "agent.db")
    m = HMArch(db_path=db_file)
    m.add("persisted episode")
    stats = m.get_stats()
    m.close()
    assert stats.storage_size_mb > 0.0


def test_get_stats_last_consolidation_from_log(mem: HMArch) -> None:
    ts = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc).isoformat()
    mem._db.execute(
        """
        INSERT INTO consolidation_log (started_at, completed_at, duration_seconds, stats)
        VALUES (?, ?, ?, ?)
        """,
        (ts, ts, 0.5, "{}"),
    )
    stats = mem.get_stats()
    assert stats.last_consolidation_at is not None
    assert stats.last_consolidation_at.year == 2024


def test_get_stats_review_queue_length(mem: HMArch) -> None:
    mem.add("important", importance=0.9)
    mid = mem._l2.encode("old episode", importance=0.9)
    mem._db.execute(
        """
        INSERT INTO review_queue (memory_id, ef, current_interval, next_review_at)
        VALUES (?, 2.5, 1, ?)
        """,
        (mid, datetime.now(tz=timezone.utc).isoformat()),
    )
    stats = mem.get_stats()
    assert stats.review_queue_length >= 1
