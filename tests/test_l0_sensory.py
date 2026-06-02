"""Tests for L0SensoryRegister.

Acceptance criteria (from HM-5):
  * L0 keeps a bounded recent window.
  * Overflow evicts oldest entries.
  * Tests pass offline (no external API keys or services required).
"""

from __future__ import annotations

import uuid
from datetime import timezone

import pytest

from hm_arch.layers.base import LayerEntry, MemoryLayer
from hm_arch.layers.l0_sensory import L0SensoryRegister, _DEFAULT_CAPACITY
from hm_arch.types import EventType, MemoryItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_register(capacity: int = 5) -> L0SensoryRegister:
    return L0SensoryRegister(capacity=capacity)


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------


class TestInstantiation:
    def test_default_capacity(self) -> None:
        reg = L0SensoryRegister()
        assert reg.capacity == _DEFAULT_CAPACITY

    def test_custom_capacity(self) -> None:
        reg = L0SensoryRegister(capacity=10)
        assert reg.capacity == 10

    def test_capacity_of_one(self) -> None:
        reg = L0SensoryRegister(capacity=1)
        assert reg.capacity == 1

    def test_invalid_capacity_zero(self) -> None:
        with pytest.raises(ValueError):
            L0SensoryRegister(capacity=0)

    def test_invalid_capacity_negative(self) -> None:
        with pytest.raises(ValueError):
            L0SensoryRegister(capacity=-3)

    def test_is_memory_layer(self) -> None:
        assert isinstance(L0SensoryRegister(), MemoryLayer)

    def test_layer_index(self) -> None:
        assert L0SensoryRegister().layer_index == 0

    def test_initial_size_is_zero(self) -> None:
        assert L0SensoryRegister().size == 0

    def test_repr(self) -> None:
        reg = L0SensoryRegister(capacity=7)
        r = repr(reg)
        assert "L0SensoryRegister" in r
        assert "0" in r  # size
        assert "7" in r  # capacity


# ---------------------------------------------------------------------------
# encode — basic behaviour
# ---------------------------------------------------------------------------


class TestEncode:
    def test_returns_string_id(self) -> None:
        reg = make_register()
        entry_id = reg.encode("hello")
        assert isinstance(entry_id, str)
        assert len(entry_id) > 0

    def test_returns_unique_ids(self) -> None:
        reg = make_register()
        ids = [reg.encode(f"item {i}") for i in range(5)]
        assert len(set(ids)) == 5

    def test_id_is_valid_uuid(self) -> None:
        reg = make_register()
        entry_id = reg.encode("test")
        uuid.UUID(entry_id)  # raises if not a valid UUID

    def test_size_increases_after_encode(self) -> None:
        reg = make_register(capacity=10)
        for i in range(4):
            reg.encode(f"item {i}")
        assert reg.size == 4

    def test_size_does_not_exceed_capacity(self) -> None:
        cap = 3
        reg = make_register(capacity=cap)
        for i in range(10):
            reg.encode(f"item {i}")
        assert reg.size == cap

    def test_encode_default_event_type(self) -> None:
        reg = make_register()
        reg.encode("test content")
        entry = reg.all_entries()[0]
        assert entry.event_type == EventType.OBSERVATION

    def test_encode_custom_event_type(self) -> None:
        reg = make_register()
        reg.encode("fix bug", event_type=EventType.CODE)
        entry = reg.all_entries()[0]
        assert entry.event_type == EventType.CODE

    def test_encode_all_event_types(self) -> None:
        reg = L0SensoryRegister(capacity=len(EventType))
        for et in EventType:
            reg.encode("test", event_type=et)
        stored_types = {e.event_type for e in reg.all_entries()}
        assert stored_types == set(EventType)

    def test_encode_stores_metadata(self) -> None:
        reg = make_register()
        reg.encode("content", metadata={"key": "value", "num": 42})
        entry = reg.all_entries()[0]
        assert entry.metadata == {"key": "value", "num": 42}

    def test_encode_none_metadata_gives_empty_dict(self) -> None:
        reg = make_register()
        reg.encode("content", metadata=None)
        entry = reg.all_entries()[0]
        assert entry.metadata == {}

    def test_encode_does_not_mutate_caller_metadata(self) -> None:
        reg = make_register()
        original = {"a": 1}
        reg.encode("content", metadata=original)
        original["a"] = 99
        entry = reg.all_entries()[0]
        assert entry.metadata["a"] == 1

    def test_added_at_is_utc(self) -> None:
        reg = make_register()
        reg.encode("content")
        entry = reg.all_entries()[0]
        assert entry.added_at.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# Bounded window — overflow / eviction
# ---------------------------------------------------------------------------


class TestBoundedWindow:
    def test_oldest_evicted_on_overflow(self) -> None:
        cap = 3
        reg = make_register(capacity=cap)
        ids = [reg.encode(f"item {i}") for i in range(5)]
        present_ids = {e.entry_id for e in reg.all_entries()}
        # First two items must have been evicted
        assert ids[0] not in present_ids
        assert ids[1] not in present_ids

    def test_newest_retained_after_overflow(self) -> None:
        cap = 3
        reg = make_register(capacity=cap)
        ids = [reg.encode(f"item {i}") for i in range(5)]
        present_ids = {e.entry_id for e in reg.all_entries()}
        for i in [2, 3, 4]:
            assert ids[i] in present_ids

    def test_exact_eviction_content(self) -> None:
        reg = make_register(capacity=2)
        reg.encode("first")
        reg.encode("second")
        reg.encode("third")  # evicts "first"
        contents = [e.content for e in reg.all_entries()]
        assert "first" not in contents
        assert "second" in contents
        assert "third" in contents

    def test_capacity_one_always_has_latest(self) -> None:
        reg = make_register(capacity=1)
        for i in range(10):
            reg.encode(f"item {i}")
        assert reg.size == 1
        assert reg.all_entries()[0].content == "item 9"

    def test_exactly_at_capacity_no_eviction(self) -> None:
        reg = make_register(capacity=4)
        ids = [reg.encode(f"item {i}") for i in range(4)]
        present_ids = {e.entry_id for e in reg.all_entries()}
        assert present_ids == set(ids)

    def test_one_over_capacity_evicts_first(self) -> None:
        reg = make_register(capacity=4)
        ids = [reg.encode(f"item {i}") for i in range(5)]
        present_ids = {e.entry_id for e in reg.all_entries()}
        assert ids[0] not in present_ids
        assert ids[1] in present_ids

    def test_insertion_order_oldest_first(self) -> None:
        reg = make_register(capacity=5)
        for i in range(5):
            reg.encode(f"item {i}")
        contents = [e.content for e in reg.all_entries()]
        assert contents == [f"item {i}" for i in range(5)]


# ---------------------------------------------------------------------------
# retrieve
# ---------------------------------------------------------------------------


class TestRetrieve:
    def test_retrieve_empty_returns_empty_list(self) -> None:
        reg = make_register()
        results = reg.retrieve("anything")
        assert results == []

    def test_retrieve_returns_memory_items(self) -> None:
        reg = make_register()
        reg.encode("Python is great")
        results = reg.retrieve("Python")
        assert len(results) == 1
        assert isinstance(results[0], MemoryItem)

    def test_retrieve_memory_item_fields(self) -> None:
        reg = make_register()
        eid = reg.encode("Python is great", metadata={"src": "test"})
        item = reg.retrieve("Python")[0]
        assert item.memory_id == eid
        assert item.layer == 0
        assert item.content == "Python is great"
        assert item.retention == 1.0
        assert 0.0 <= item.relevance <= 1.0
        assert 0.0 <= item.score <= 1.0
        assert item.metadata == {"src": "test"}

    def test_retrieve_top_k_limits_results(self) -> None:
        reg = L0SensoryRegister(capacity=20)
        for i in range(10):
            reg.encode(f"Python item {i}")
        results = reg.retrieve("Python", top_k=3)
        assert len(results) <= 3

    def test_retrieve_default_top_k_is_five(self) -> None:
        reg = L0SensoryRegister(capacity=20)
        for i in range(10):
            reg.encode(f"Python item {i}")
        results = reg.retrieve("Python")
        assert len(results) <= 5

    def test_retrieve_relevant_item_scores_higher(self) -> None:
        reg = L0SensoryRegister(capacity=10)
        reg.encode("Python programming language")
        reg.encode("unrelated topic about cooking")
        results = reg.retrieve("Python programming", top_k=10)
        scores = {r.content: r.score for r in results}
        assert scores["Python programming language"] > scores["unrelated topic about cooking"]

    def test_retrieve_zero_relevance_for_disjoint_query(self) -> None:
        reg = make_register()
        reg.encode("Python is great")
        results = reg.retrieve("zzzzzzz_nomatch_zzzzzzz")
        # Score can be 0 (no overlap)
        assert all(r.score == 0.0 for r in results)

    def test_retrieve_sorted_by_score_descending(self) -> None:
        reg = L0SensoryRegister(capacity=10)
        reg.encode("Python Python Python")
        reg.encode("Python once")
        reg.encode("unrelated content here")
        results = reg.retrieve("Python", top_k=10)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_retrieve_deterministic(self) -> None:
        reg = L0SensoryRegister(capacity=10)
        for i in range(5):
            reg.encode(f"Python item {i}")
        r1 = reg.retrieve("Python", top_k=5)
        r2 = reg.retrieve("Python", top_k=5)
        assert [x.memory_id for x in r1] == [x.memory_id for x in r2]

    def test_retrieve_metadata_isolated_from_internal_state(self) -> None:
        reg = make_register()
        reg.encode("test", metadata={"key": "original"})
        item = reg.retrieve("test")[0]
        item.metadata["key"] = "mutated"
        # Retrieve again — internal state must be unchanged
        item2 = reg.retrieve("test")[0]
        assert item2.metadata["key"] == "original"

    def test_retrieve_layer_index_is_zero(self) -> None:
        reg = make_register()
        reg.encode("something")
        results = reg.retrieve("something")
        assert all(r.layer == 0 for r in results)

    def test_retrieve_all_have_retention_one(self) -> None:
        reg = make_register()
        reg.encode("memory item")
        results = reg.retrieve("memory")
        assert all(r.retention == 1.0 for r in results)

    def test_retrieve_top_k_larger_than_window(self) -> None:
        reg = make_register(capacity=3)
        reg.encode("item a")
        reg.encode("item b")
        results = reg.retrieve("item", top_k=100)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


class TestClear:
    def test_clear_empties_window(self) -> None:
        reg = make_register()
        for i in range(4):
            reg.encode(f"item {i}")
        reg.clear()
        assert reg.size == 0

    def test_clear_retrieve_returns_empty(self) -> None:
        reg = make_register()
        reg.encode("some content")
        reg.clear()
        assert reg.retrieve("some") == []

    def test_clear_then_encode_works(self) -> None:
        reg = make_register()
        for i in range(5):
            reg.encode(f"item {i}")
        reg.clear()
        eid = reg.encode("fresh item")
        assert reg.size == 1
        assert reg.all_entries()[0].entry_id == eid

    def test_clear_does_not_change_capacity(self) -> None:
        reg = make_register(capacity=7)
        reg.encode("test")
        reg.clear()
        assert reg.capacity == 7


# ---------------------------------------------------------------------------
# all_entries
# ---------------------------------------------------------------------------


class TestAllEntries:
    def test_all_entries_empty(self) -> None:
        assert make_register().all_entries() == []

    def test_all_entries_returns_layer_entries(self) -> None:
        reg = make_register()
        reg.encode("item")
        entries = reg.all_entries()
        assert all(isinstance(e, LayerEntry) for e in entries)

    def test_all_entries_oldest_first(self) -> None:
        reg = make_register(capacity=5)
        for i in range(5):
            reg.encode(f"item {i}")
        entries = reg.all_entries()
        contents = [e.content for e in entries]
        assert contents == ["item 0", "item 1", "item 2", "item 3", "item 4"]

    def test_all_entries_does_not_mutate_internal_state(self) -> None:
        reg = make_register(capacity=5)
        reg.encode("a")
        entries = reg.all_entries()
        entries.clear()
        assert reg.size == 1


# ---------------------------------------------------------------------------
# __len__ dunder
# ---------------------------------------------------------------------------


class TestLen:
    def test_len_matches_size(self) -> None:
        reg = make_register(capacity=10)
        for i in range(6):
            reg.encode(f"item {i}")
        assert len(reg) == reg.size

    def test_len_empty(self) -> None:
        assert len(make_register()) == 0

    def test_len_at_capacity(self) -> None:
        reg = make_register(capacity=4)
        for i in range(4):
            reg.encode(f"item {i}")
        assert len(reg) == 4


# ---------------------------------------------------------------------------
# Integration: large overflow scenario
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_overflow_many_times(self) -> None:
        cap = 5
        reg = make_register(capacity=cap)
        all_ids: list[str] = []
        for i in range(50):
            eid = reg.encode(f"event {i}")
            all_ids.append(eid)

        assert reg.size == cap
        present = {e.entry_id for e in reg.all_entries()}
        # Only the last `cap` IDs should be present
        assert present == set(all_ids[-cap:])

    def test_encode_retrieve_cycle(self) -> None:
        reg = L0SensoryRegister(capacity=10)
        reg.encode("User prefers Python")
        reg.encode("User dislikes Java")
        reg.encode("Weather is sunny today")

        results = reg.retrieve("Python preference", top_k=5)
        top_content = [r.content for r in results]
        assert "User prefers Python" in top_content
        assert results[0].content == "User prefers Python"
