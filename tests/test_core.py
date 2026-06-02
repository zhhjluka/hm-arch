"""Tests for the HMArch public facade (add / search).

All tests use an in-memory SQLite database so they are fully offline and
leave no files on disk.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from hm_arch import (
    HMArch,
    EventType,
    MemoryItem,
    MemoryReceipt,
    SearchResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mem() -> HMArch:
    """Return a fresh in-memory HMArch instance for each test."""
    m = HMArch(db_path=":memory:")
    yield m
    m.close()


# ---------------------------------------------------------------------------
# HMArch.add()
# ---------------------------------------------------------------------------


class TestAdd:
    def test_returns_memory_receipt(self, mem: HMArch) -> None:
        receipt = mem.add("hello world")
        assert isinstance(receipt, MemoryReceipt)

    def test_receipt_has_non_empty_memory_id(self, mem: HMArch) -> None:
        receipt = mem.add("hello world")
        assert isinstance(receipt.memory_id, str)
        assert len(receipt.memory_id) > 0

    def test_receipt_layer_is_two(self, mem: HMArch) -> None:
        receipt = mem.add("persistent memory")
        assert receipt.layer == 2

    def test_receipt_importance_in_unit_interval(self, mem: HMArch) -> None:
        receipt = mem.add("some content")
        assert 0.0 <= receipt.importance <= 1.0

    def test_receipt_initial_strength_in_unit_interval(self, mem: HMArch) -> None:
        receipt = mem.add("some content")
        assert 0.0 <= receipt.initial_strength <= 1.0

    def test_receipt_decay_estimate_has_all_checkpoints(self, mem: HMArch) -> None:
        receipt = mem.add("some content")
        assert "1d" in receipt.decay_estimate
        assert "7d" in receipt.decay_estimate
        assert "30d" in receipt.decay_estimate

    def test_decay_estimate_values_decrease_over_time(self, mem: HMArch) -> None:
        receipt = mem.add("some content")
        assert receipt.decay_estimate["1d"] > receipt.decay_estimate["7d"]
        assert receipt.decay_estimate["7d"] > receipt.decay_estimate["30d"]

    def test_decay_estimate_values_in_unit_interval(self, mem: HMArch) -> None:
        receipt = mem.add("some content")
        for val in receipt.decay_estimate.values():
            assert 0.0 <= val <= 1.0

    def test_consolidation_scheduled_is_future_datetime(self, mem: HMArch) -> None:
        before = datetime.now(tz=__import__("datetime").timezone.utc)
        receipt = mem.add("some content")
        assert isinstance(receipt.consolidation_scheduled, datetime)
        assert receipt.consolidation_scheduled > before

    def test_add_stores_in_l2(self, mem: HMArch) -> None:
        mem.add("persistent content")
        assert mem._l2.count() == 1

    def test_add_stores_in_l1(self, mem: HMArch) -> None:
        mem.add("in-memory content")
        assert mem._l1.size == 1

    def test_multiple_adds_increase_l2_count(self, mem: HMArch) -> None:
        for i in range(5):
            mem.add(f"item {i}")
        assert mem._l2.count() == 5

    def test_add_with_event_type(self, mem: HMArch) -> None:
        receipt = mem.add("user prefers Python", event_type=EventType.CONVERSATION)
        assert isinstance(receipt, MemoryReceipt)

    def test_add_with_metadata(self, mem: HMArch) -> None:
        receipt = mem.add("content with metadata", metadata={"source": "test"})
        assert isinstance(receipt, MemoryReceipt)

    def test_add_cjk_content(self, mem: HMArch) -> None:
        receipt = mem.add("用户偏好 Python")
        assert isinstance(receipt, MemoryReceipt)
        assert receipt.layer == 2

    def test_unique_memory_ids_per_add(self, mem: HMArch) -> None:
        r1 = mem.add("first")
        r2 = mem.add("second")
        assert r1.memory_id != r2.memory_id


# ---------------------------------------------------------------------------
# HMArch.search()
# ---------------------------------------------------------------------------


class TestSearch:
    def test_returns_search_result(self, mem: HMArch) -> None:
        mem.add("Python programming")
        result = mem.search("Python")
        assert isinstance(result, SearchResult)

    def test_results_is_list_of_memory_items(self, mem: HMArch) -> None:
        mem.add("hello world")
        result = mem.search("hello")
        assert isinstance(result.results, list)
        for item in result.results:
            assert isinstance(item, MemoryItem)

    def test_finds_added_memory(self, mem: HMArch) -> None:
        mem.add("Python programming language")
        result = mem.search("Python")
        assert len(result.results) > 0
        contents = [item.content for item in result.results]
        assert any("Python" in c for c in contents)

    def test_results_sorted_descending_by_score(self, mem: HMArch) -> None:
        mem.add("Python is excellent for scripting")
        mem.add("unrelated term zzzzzz")
        result = mem.search("Python scripting")
        scores = [item.score for item in result.results]
        assert scores == sorted(scores, reverse=True)

    def test_memory_item_layer_field(self, mem: HMArch) -> None:
        mem.add("test content")
        result = mem.search("test")
        for item in result.results:
            assert item.layer in (1, 2, 3)

    def test_memory_item_retention_in_unit_interval(self, mem: HMArch) -> None:
        mem.add("test content")
        result = mem.search("test")
        for item in result.results:
            assert 0.0 <= item.retention <= 1.0

    def test_memory_item_relevance_in_unit_interval(self, mem: HMArch) -> None:
        mem.add("test content")
        result = mem.search("test")
        for item in result.results:
            assert 0.0 <= item.relevance <= 1.0

    def test_memory_item_score_in_unit_interval(self, mem: HMArch) -> None:
        mem.add("test content")
        result = mem.search("test")
        for item in result.results:
            assert 0.0 <= item.score <= 1.0

    def test_total_scanned_is_non_negative_int(self, mem: HMArch) -> None:
        mem.add("hello")
        result = mem.search("hello")
        assert isinstance(result.total_scanned, int)
        assert result.total_scanned >= 0

    def test_timing_ms_is_positive(self, mem: HMArch) -> None:
        mem.add("hello")
        result = mem.search("hello")
        assert isinstance(result.timing_ms, float)
        assert result.timing_ms >= 0.0

    def test_source_breakdown_is_dict(self, mem: HMArch) -> None:
        mem.add("hello")
        result = mem.search("hello")
        assert isinstance(result.source_breakdown, dict)

    def test_empty_store_returns_empty_results(self, mem: HMArch) -> None:
        result = mem.search("nothing here")
        assert result.results == []

    def test_top_k_limits_results(self, mem: HMArch) -> None:
        for i in range(10):
            mem.add(f"memory item number {i} about Python")
        result = mem.search("Python", top_k=3)
        assert len(result.results) <= 3

    def test_cjk_add_found_by_partial_cjk_query(self, mem: HMArch) -> None:
        """Acceptance criterion: add('用户偏好 Python') found by search('用户偏好')."""
        mem.add("用户偏好 Python")
        result = mem.search("用户偏好")
        assert len(result.results) > 0
        contents = [item.content for item in result.results]
        assert any("用户偏好" in c for c in contents)

    def test_search_result_includes_source_layer(self, mem: HMArch) -> None:
        mem.add("hello world")
        result = mem.search("hello")
        assert len(result.results) > 0
        assert all(hasattr(item, "layer") for item in result.results)

    def test_context_manager_usage(self) -> None:
        with HMArch(db_path=":memory:") as memory:
            memory.add("context manager test")
            result = memory.search("context manager")
            assert len(result.results) > 0
