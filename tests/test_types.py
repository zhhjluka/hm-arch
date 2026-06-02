"""Tests for public dataclasses and EventType defined in types.py.

Each test validates the exact PRD field names and constructor signatures so
that later implementation modules cannot silently diverge from the contract.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest

from hm_arch import (
    ConsolidationReport,
    EventType,
    ForgetResult,
    MemoryItem,
    MemoryReceipt,
    MemoryStats,
    RetentionCurve,
    SearchResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _field_names(cls: type) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


# ---------------------------------------------------------------------------
# EventType — values required by PRD examples
# ---------------------------------------------------------------------------


def test_event_type_required_members() -> None:
    """PRD examples use at least these four values."""
    for name in ("CONVERSATION", "OBSERVATION", "DECISION", "ERROR"):
        assert hasattr(EventType, name), f"EventType.{name} is missing"


def test_event_type_is_str_subclass() -> None:
    for member in EventType:
        assert isinstance(member, str), f"{member!r} is not a str"


def test_event_type_conversation_value() -> None:
    assert EventType.CONVERSATION == "conversation"


def test_event_type_all_members_documented() -> None:
    """Guard against typos: every member value must be lowercase."""
    for member in EventType:
        assert member.value == member.value.lower(), (
            f"EventType.{member.name} value {member.value!r} is not lowercase"
        )


# ---------------------------------------------------------------------------
# MemoryReceipt — PRD shape
# ---------------------------------------------------------------------------


class TestMemoryReceipt:
    REQUIRED_FIELDS = {
        "memory_id",
        "layer",
        "importance",
        "initial_strength",
        "decay_estimate",
        "consolidation_scheduled",
    }

    def test_fields_present(self) -> None:
        assert self.REQUIRED_FIELDS <= _field_names(MemoryReceipt)

    def test_construction(self) -> None:
        receipt = MemoryReceipt(
            memory_id="mr-001",
            layer=2,
            importance=0.75,
            initial_strength=1.0,
            decay_estimate={"1d": 0.92, "7d": 0.65, "30d": 0.28},
            consolidation_scheduled=_now(),
        )
        assert receipt.memory_id == "mr-001"
        assert receipt.layer == 2
        assert receipt.importance == pytest.approx(0.75)
        assert isinstance(receipt.decay_estimate, dict)
        assert isinstance(receipt.consolidation_scheduled, datetime)


# ---------------------------------------------------------------------------
# MemoryItem — PRD shape (individual hit inside SearchResult)
# ---------------------------------------------------------------------------


class TestMemoryItem:
    REQUIRED_FIELDS = {
        "memory_id",
        "layer",
        "content",
        "retention",
        "relevance",
        "score",
        "metadata",
    }

    def test_fields_present(self) -> None:
        assert self.REQUIRED_FIELDS <= _field_names(MemoryItem)

    def test_construction_with_metadata(self) -> None:
        item = MemoryItem(
            memory_id="mi-001",
            layer=3,
            content="user likes Python",
            retention=0.85,
            relevance=0.90,
            score=0.76,
            metadata={"source": "l3_semantic"},
        )
        assert item.layer == 3
        assert item.content == "user likes Python"
        assert item.score == pytest.approx(0.76)
        assert item.metadata["source"] == "l3_semantic"

    def test_metadata_defaults_to_empty_dict(self) -> None:
        item = MemoryItem(
            memory_id="mi-002",
            layer=2,
            content="task complete",
            retention=0.7,
            relevance=0.8,
            score=0.56,
        )
        assert item.metadata == {}


# ---------------------------------------------------------------------------
# SearchResult — PRD wrapper shape (not a single hit)
# ---------------------------------------------------------------------------


class TestSearchResult:
    REQUIRED_FIELDS = {
        "results",
        "total_scanned",
        "timing_ms",
        "source_breakdown",
    }

    def _make_item(self) -> MemoryItem:
        return MemoryItem(
            memory_id="mi-x",
            layer=2,
            content="sample",
            retention=0.8,
            relevance=0.9,
            score=0.72,
        )

    def test_fields_present(self) -> None:
        assert self.REQUIRED_FIELDS <= _field_names(SearchResult)

    def test_construction(self) -> None:
        sr = SearchResult(
            results=[self._make_item()],
            total_scanned=100,
            timing_ms=12.5,
            source_breakdown={0: 5, 1: 10, 2: 40, 3: 45},
        )
        assert len(sr.results) == 1
        assert isinstance(sr.results[0], MemoryItem)
        assert sr.total_scanned == 100
        assert sr.timing_ms == pytest.approx(12.5)
        assert sr.source_breakdown[2] == 40

    def test_results_is_list_of_memory_items(self) -> None:
        sr = SearchResult(
            results=[self._make_item(), self._make_item()],
            total_scanned=50,
            timing_ms=5.0,
            source_breakdown={},
        )
        for item in sr.results:
            assert isinstance(item, MemoryItem)


# ---------------------------------------------------------------------------
# ConsolidationReport — PRD shape
# ---------------------------------------------------------------------------


class TestConsolidationReport:
    REQUIRED_FIELDS = {
        "extracted_semantics",
        "merged_duplicates",
        "resolved_conflicts",
        "archived_to_l4",
        "scheduled_reviews",
        "marked_deletable",
        "duration_seconds",
    }

    def test_fields_present(self) -> None:
        assert self.REQUIRED_FIELDS <= _field_names(ConsolidationReport)

    def test_construction(self) -> None:
        report = ConsolidationReport(
            extracted_semantics=8,
            merged_duplicates=2,
            resolved_conflicts=1,
            archived_to_l4=3,
            scheduled_reviews=5,
            marked_deletable=0,
            duration_seconds=0.73,
        )
        assert report.extracted_semantics == 8
        assert report.merged_duplicates == 2
        assert report.resolved_conflicts == 1
        assert report.archived_to_l4 == 3
        assert report.scheduled_reviews == 5
        assert report.marked_deletable == 0
        assert report.duration_seconds == pytest.approx(0.73)


# ---------------------------------------------------------------------------
# RetentionCurve — PRD shape
# ---------------------------------------------------------------------------


class TestRetentionCurve:
    REQUIRED_FIELDS = {
        "days",
        "retention",
        "review_suggested_at_day",
        "archive_at_day",
    }

    def test_fields_present(self) -> None:
        assert self.REQUIRED_FIELDS <= _field_names(RetentionCurve)

    def test_construction(self) -> None:
        curve = RetentionCurve(
            days=[0, 1, 7, 14, 30, 60],
            retention=[1.0, 0.90, 0.70, 0.58, 0.40, 0.26],
            review_suggested_at_day=10,
            archive_at_day=45,
        )
        assert curve.days[0] == 0
        assert curve.retention[0] == pytest.approx(1.0)
        assert len(curve.days) == len(curve.retention)
        assert curve.review_suggested_at_day == 10
        assert curve.archive_at_day == 45


# ---------------------------------------------------------------------------
# MemoryStats — PRD shape
# ---------------------------------------------------------------------------


class TestMemoryStats:
    REQUIRED_FIELDS = {
        "total_memories",
        "by_layer",
        "storage_size_mb",
        "retention_distribution",
        "review_queue_length",
        "last_consolidation_at",
    }

    def test_fields_present(self) -> None:
        assert self.REQUIRED_FIELDS <= _field_names(MemoryStats)

    def test_construction(self) -> None:
        stats = MemoryStats(
            total_memories=100,
            by_layer={0: 5, 1: 15, 2: 60, 3: 20},
            storage_size_mb=1.25,
            retention_distribution={"0-0.25": 10, "0.25-0.75": 60, "0.75-1.0": 30},
            review_queue_length=7,
            last_consolidation_at=_now(),
        )
        assert stats.total_memories == 100
        assert stats.by_layer[2] == 60
        assert stats.storage_size_mb == pytest.approx(1.25)
        assert stats.review_queue_length == 7
        assert isinstance(stats.last_consolidation_at, datetime)

    def test_last_consolidation_at_nullable(self) -> None:
        stats = MemoryStats(
            total_memories=0,
            by_layer={},
            storage_size_mb=0.0,
            retention_distribution={},
            review_queue_length=0,
            last_consolidation_at=None,
        )
        assert stats.last_consolidation_at is None


# ---------------------------------------------------------------------------
# ForgetResult — PRD shape
# ---------------------------------------------------------------------------


class TestForgetResult:
    REQUIRED_FIELDS = {
        "forgotten_count",
        "archived_count",
        "freed_memory_mb",
        "affected_layers",
        "details",
    }

    def test_fields_present(self) -> None:
        assert self.REQUIRED_FIELDS <= _field_names(ForgetResult)

    def test_construction(self) -> None:
        result = ForgetResult(
            forgotten_count=3,
            archived_count=1,
            freed_memory_mb=0.05,
            affected_layers=[2, 3],
            details=[
                {"memory_id": "m-1", "action": "deleted"},
                {"memory_id": "m-2", "action": "archived"},
            ],
        )
        assert result.forgotten_count == 3
        assert result.archived_count == 1
        assert result.freed_memory_mb == pytest.approx(0.05)
        assert 2 in result.affected_layers
        assert result.details[0]["action"] == "deleted"


# ---------------------------------------------------------------------------
# Top-level importability
# ---------------------------------------------------------------------------


def test_all_types_exported_from_hm_arch() -> None:
    import hm_arch

    expected = {
        "EventType",
        "MemoryReceipt",
        "MemoryItem",
        "SearchResult",
        "ConsolidationReport",
        "RetentionCurve",
        "MemoryStats",
        "ForgetResult",
    }
    for name in expected:
        assert hasattr(hm_arch, name), f"hm_arch.{name} not found"
        assert name in hm_arch.__all__, f"{name} missing from __all__"
