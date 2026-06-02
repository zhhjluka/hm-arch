"""Tests for public dataclasses and EventType defined in types.py."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from hm_arch import (
    ConsolidationReport,
    EventType,
    MemoryItem,
    MemoryReceipt,
    MemoryStats,
    RetentionCurve,
    SearchResult,
)


# ---------------------------------------------------------------------------
# EventType
# ---------------------------------------------------------------------------


def test_event_type_members_exist() -> None:
    expected = {"CONVERSATION", "CODE", "DECISION", "TASK", "OBSERVATION", "ERROR", "SYSTEM"}
    actual = {m.name for m in EventType}
    assert expected == actual


def test_event_type_is_str() -> None:
    for member in EventType:
        assert isinstance(member.value, str), f"{member} value is not a str"


def test_event_type_conversation_value() -> None:
    assert EventType.CONVERSATION == "conversation"


# ---------------------------------------------------------------------------
# MemoryReceipt
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def test_memory_receipt_construction() -> None:
    receipt = MemoryReceipt(
        memory_id="abc-123",
        timestamp=_now(),
        event_type=EventType.CODE,
        layer="L2",
        content_preview="def foo():",
    )
    assert receipt.memory_id == "abc-123"
    assert receipt.event_type == EventType.CODE
    assert receipt.layer == "L2"
    assert receipt.content_preview == "def foo():"


# ---------------------------------------------------------------------------
# MemoryItem
# ---------------------------------------------------------------------------


def test_memory_item_defaults_metadata() -> None:
    item = MemoryItem(
        memory_id="m-1",
        content="user likes Python",
        event_type=EventType.CONVERSATION,
        layer="L3",
        timestamp=_now(),
        retention=0.9,
        importance=0.7,
    )
    assert item.metadata == {}


def test_memory_item_with_metadata() -> None:
    item = MemoryItem(
        memory_id="m-2",
        content="task done",
        event_type=EventType.TASK,
        layer="L2",
        timestamp=_now(),
        retention=0.5,
        importance=0.6,
        metadata={"source": "test"},
    )
    assert item.metadata["source"] == "test"


# ---------------------------------------------------------------------------
# SearchResult
# ---------------------------------------------------------------------------


def test_search_result_fields() -> None:
    result = SearchResult(
        memory_id="sr-1",
        content="Python is the preferred language",
        score=0.85,
        relevance=0.9,
        retention=0.95,
        layer="L3",
        event_type=EventType.CONVERSATION,
        timestamp=_now(),
    )
    assert 0.0 <= result.score <= 1.0
    assert result.layer == "L3"


# ---------------------------------------------------------------------------
# ConsolidationReport
# ---------------------------------------------------------------------------


def test_consolidation_report_fields() -> None:
    report = ConsolidationReport(
        consolidated_episodes=10,
        semantic_triples_created=3,
        semantic_triples_merged=1,
        memories_scheduled_for_review=2,
        duration_s=0.42,
        timestamp=_now(),
    )
    assert report.consolidated_episodes == 10
    assert report.semantic_triples_created == 3
    assert report.duration_s == pytest.approx(0.42)


# ---------------------------------------------------------------------------
# RetentionCurve
# ---------------------------------------------------------------------------


def test_retention_curve_fields() -> None:
    curve = RetentionCurve(
        memory_id="rc-1",
        layer="L2",
        timestamps_days=[0.0, 1.0, 7.0, 30.0],
        retention_values=[1.0, 0.85, 0.60, 0.26],
        half_life_days=5.5,
    )
    assert len(curve.timestamps_days) == len(curve.retention_values)
    assert curve.retention_values[0] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# MemoryStats
# ---------------------------------------------------------------------------


def test_memory_stats_fields() -> None:
    stats = MemoryStats(
        total_memories=42,
        by_layer={"L0": 5, "L1": 10, "L2": 20, "L3": 7},
        by_event_type={"conversation": 30, "code": 12},
        db_size_bytes=4096,
        oldest_memory=_now(),
        newest_memory=_now(),
    )
    assert stats.total_memories == 42
    assert stats.by_layer["L2"] == 20


def test_memory_stats_optional_datetimes() -> None:
    stats = MemoryStats(
        total_memories=0,
        by_layer={},
        by_event_type={},
        db_size_bytes=0,
        oldest_memory=None,
        newest_memory=None,
    )
    assert stats.oldest_memory is None
    assert stats.newest_memory is None


# ---------------------------------------------------------------------------
# Importability from top-level package
# ---------------------------------------------------------------------------


def test_all_types_importable_from_hm_arch() -> None:
    import hm_arch

    for name in (
        "EventType",
        "MemoryReceipt",
        "MemoryItem",
        "SearchResult",
        "ConsolidationReport",
        "RetentionCurve",
        "MemoryStats",
    ):
        assert hasattr(hm_arch, name), f"hm_arch.{name} not found"
        assert name in hm_arch.__all__, f"{name} missing from __all__"
