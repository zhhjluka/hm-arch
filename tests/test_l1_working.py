"""Tests for L1WorkingMemory.

Acceptance criteria (from HM-5):
  * L1 keeps bounded session items.
  * Overflow evicts oldest entries.
  * Tests pass offline (no external API keys or services required).
"""

from __future__ import annotations

import uuid
from datetime import timezone

import pytest

from hm_arch.layers.base import LayerEntry, MemoryLayer
from hm_arch.layers.l1_working import L1WorkingMemory, _DEFAULT_CAPACITY, _LAYER_PRIORITY
from hm_arch.types import EventType, MemoryItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_wm(capacity: int = 5) -> L1WorkingMemory:
    return L1WorkingMemory(capacity=capacity)


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------


class TestInstantiation:
    def test_default_capacity(self) -> None:
        wm = L1WorkingMemory()
        assert wm.capacity == _DEFAULT_CAPACITY

    def test_custom_capacity(self) -> None:
        wm = L1WorkingMemory(capacity=20)
        assert wm.capacity == 20

    def test_capacity_of_one(self) -> None:
        wm = L1WorkingMemory(capacity=1)
        assert wm.capacity == 1

    def test_invalid_capacity_zero(self) -> None:
        with pytest.raises(ValueError):
            L1WorkingMemory(capacity=0)

    def test_invalid_capacity_negative(self) -> None:
        with pytest.raises(ValueError):
            L1WorkingMemory(capacity=-1)

    def test_is_memory_layer(self) -> None:
        assert isinstance(L1WorkingMemory(), MemoryLayer)

    def test_layer_index(self) -> None:
        assert L1WorkingMemory().layer_index == 1

    def test_layer_index_differs_from_l0(self) -> None:
        from hm_arch.layers.l0_sensory import L0SensoryRegister
        assert L1WorkingMemory().layer_index != L0SensoryRegister().layer_index

    def test_initial_size_is_zero(self) -> None:
        assert L1WorkingMemory().size == 0

    def test_repr(self) -> None:
        wm = L1WorkingMemory(capacity=12)
        r = repr(wm)
        assert "L1WorkingMemory" in r
        assert "0" in r  # size
        assert "12" in r  # capacity


# ---------------------------------------------------------------------------
# encode — basic behaviour
# ---------------------------------------------------------------------------


class TestEncode:
    def test_returns_string_id(self) -> None:
        wm = make_wm()
        entry_id = wm.encode("hello")
        assert isinstance(entry_id, str)
        assert len(entry_id) > 0

    def test_returns_unique_ids(self) -> None:
        wm = make_wm()
        ids = [wm.encode(f"item {i}") for i in range(5)]
        assert len(set(ids)) == 5

    def test_id_is_valid_uuid(self) -> None:
        wm = make_wm()
        entry_id = wm.encode("test")
        uuid.UUID(entry_id)

    def test_size_increases_after_encode(self) -> None:
        wm = make_wm(capacity=10)
        for i in range(4):
            wm.encode(f"item {i}")
        assert wm.size == 4

    def test_size_does_not_exceed_capacity(self) -> None:
        cap = 4
        wm = make_wm(capacity=cap)
        for i in range(20):
            wm.encode(f"item {i}")
        assert wm.size == cap

    def test_encode_default_event_type(self) -> None:
        wm = make_wm()
        wm.encode("some work")
        entry = wm.all_entries()[0]
        assert entry.event_type == EventType.OBSERVATION

    def test_encode_custom_event_type(self) -> None:
        wm = make_wm()
        wm.encode("decided to refactor", event_type=EventType.DECISION)
        entry = wm.all_entries()[0]
        assert entry.event_type == EventType.DECISION

    def test_encode_all_event_types(self) -> None:
        wm = L1WorkingMemory(capacity=len(EventType))
        for et in EventType:
            wm.encode("test", event_type=et)
        stored_types = {e.event_type for e in wm.all_entries()}
        assert stored_types == set(EventType)

    def test_encode_stores_metadata(self) -> None:
        wm = make_wm()
        wm.encode("work item", metadata={"priority": "high", "tag": "bug"})
        entry = wm.all_entries()[0]
        assert entry.metadata == {"priority": "high", "tag": "bug"}

    def test_encode_none_metadata_gives_empty_dict(self) -> None:
        wm = make_wm()
        wm.encode("work item", metadata=None)
        assert wm.all_entries()[0].metadata == {}

    def test_encode_does_not_mutate_caller_metadata(self) -> None:
        wm = make_wm()
        original = {"x": 10}
        wm.encode("test", metadata=original)
        original["x"] = 999
        assert wm.all_entries()[0].metadata["x"] == 10

    def test_added_at_is_utc(self) -> None:
        wm = make_wm()
        wm.encode("content")
        entry = wm.all_entries()[0]
        assert entry.added_at.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# Bounded buffer — overflow / eviction
# ---------------------------------------------------------------------------


class TestBoundedBuffer:
    def test_oldest_evicted_on_overflow(self) -> None:
        cap = 3
        wm = make_wm(capacity=cap)
        ids = [wm.encode(f"item {i}") for i in range(5)]
        present_ids = {e.entry_id for e in wm.all_entries()}
        assert ids[0] not in present_ids
        assert ids[1] not in present_ids

    def test_newest_retained_after_overflow(self) -> None:
        cap = 3
        wm = make_wm(capacity=cap)
        ids = [wm.encode(f"item {i}") for i in range(5)]
        present_ids = {e.entry_id for e in wm.all_entries()}
        for i in [2, 3, 4]:
            assert ids[i] in present_ids

    def test_exact_eviction_content(self) -> None:
        wm = make_wm(capacity=2)
        wm.encode("first")
        wm.encode("second")
        wm.encode("third")  # evicts "first"
        contents = [e.content for e in wm.all_entries()]
        assert "first" not in contents
        assert "second" in contents
        assert "third" in contents

    def test_capacity_one_always_has_latest(self) -> None:
        wm = make_wm(capacity=1)
        for i in range(10):
            wm.encode(f"item {i}")
        assert wm.size == 1
        assert wm.all_entries()[0].content == "item 9"

    def test_exactly_at_capacity_no_eviction(self) -> None:
        wm = make_wm(capacity=4)
        ids = [wm.encode(f"item {i}") for i in range(4)]
        present_ids = {e.entry_id for e in wm.all_entries()}
        assert present_ids == set(ids)

    def test_one_over_capacity_evicts_first(self) -> None:
        wm = make_wm(capacity=4)
        ids = [wm.encode(f"item {i}") for i in range(5)]
        present_ids = {e.entry_id for e in wm.all_entries()}
        assert ids[0] not in present_ids
        assert ids[1] in present_ids

    def test_insertion_order_oldest_first(self) -> None:
        wm = make_wm(capacity=5)
        for i in range(5):
            wm.encode(f"item {i}")
        contents = [e.content for e in wm.all_entries()]
        assert contents == [f"item {i}" for i in range(5)]


# ---------------------------------------------------------------------------
# retrieve
# ---------------------------------------------------------------------------


class TestRetrieve:
    def test_retrieve_empty_returns_empty_list(self) -> None:
        wm = make_wm()
        assert wm.retrieve("anything") == []

    def test_retrieve_returns_memory_items(self) -> None:
        wm = make_wm()
        wm.encode("task planning session")
        results = wm.retrieve("task")
        assert len(results) == 1
        assert isinstance(results[0], MemoryItem)

    def test_retrieve_memory_item_fields(self) -> None:
        wm = make_wm()
        eid = wm.encode("working on feature X", metadata={"sprint": 3})
        item = wm.retrieve("feature")[0]
        assert item.memory_id == eid
        assert item.layer == 1
        assert item.content == "working on feature X"
        assert item.retention == 1.0
        assert 0.0 <= item.relevance <= 1.0
        assert 0.0 <= item.score <= 1.0
        assert item.metadata == {"sprint": 3}

    def test_retrieve_layer_index_is_one(self) -> None:
        wm = make_wm()
        wm.encode("something")
        results = wm.retrieve("something")
        assert all(r.layer == 1 for r in results)

    def test_retrieve_top_k_limits_results(self) -> None:
        wm = L1WorkingMemory(capacity=20)
        for i in range(10):
            wm.encode(f"Python task {i}")
        results = wm.retrieve("Python", top_k=3)
        assert len(results) <= 3

    def test_retrieve_default_top_k_is_five(self) -> None:
        wm = L1WorkingMemory(capacity=20)
        for i in range(10):
            wm.encode(f"Python task {i}")
        results = wm.retrieve("Python")
        assert len(results) <= 5

    def test_retrieve_relevant_item_scores_higher(self) -> None:
        wm = L1WorkingMemory(capacity=10)
        wm.encode("implement Python algorithm")
        wm.encode("order coffee and lunch")
        results = wm.retrieve("Python algorithm", top_k=10)
        scores = {r.content: r.score for r in results}
        assert scores["implement Python algorithm"] > scores["order coffee and lunch"]

    def test_retrieve_zero_relevance_for_disjoint_query(self) -> None:
        wm = make_wm()
        wm.encode("Python is great")
        results = wm.retrieve("zzzzzzz_nomatch_zzzzzzz")
        assert all(r.score == 0.0 for r in results)

    def test_retrieve_sorted_by_score_descending(self) -> None:
        wm = L1WorkingMemory(capacity=10)
        wm.encode("Python Python Python task")
        wm.encode("Python task")
        wm.encode("unrelated item here")
        results = wm.retrieve("Python", top_k=10)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_retrieve_deterministic(self) -> None:
        wm = L1WorkingMemory(capacity=10)
        for i in range(5):
            wm.encode(f"session item {i}")
        r1 = wm.retrieve("session item", top_k=5)
        r2 = wm.retrieve("session item", top_k=5)
        assert [x.memory_id for x in r1] == [x.memory_id for x in r2]

    def test_retrieve_metadata_isolated_from_internal_state(self) -> None:
        wm = make_wm()
        wm.encode("test", metadata={"key": "original"})
        item = wm.retrieve("test")[0]
        item.metadata["key"] = "mutated"
        item2 = wm.retrieve("test")[0]
        assert item2.metadata["key"] == "original"

    def test_retrieve_all_have_retention_one(self) -> None:
        wm = make_wm()
        wm.encode("working memory entry")
        results = wm.retrieve("memory")
        assert all(r.retention == 1.0 for r in results)

    def test_retrieve_top_k_larger_than_buffer(self) -> None:
        wm = make_wm(capacity=3)
        wm.encode("item alpha")
        wm.encode("item beta")
        results = wm.retrieve("item", top_k=100)
        assert len(results) == 2

    def test_layer_priority_reflected_in_score(self) -> None:
        """L1 scores should reflect the 0.9 layer priority."""
        wm = make_wm()
        wm.encode("exact match exact match")
        results = wm.retrieve("exact match")
        # Score = retention(1.0) * relevance * 0.9 — must be <= 0.9
        assert all(r.score <= _LAYER_PRIORITY + 1e-9 for r in results)


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


class TestClear:
    def test_clear_empties_buffer(self) -> None:
        wm = make_wm()
        for i in range(4):
            wm.encode(f"item {i}")
        wm.clear()
        assert wm.size == 0

    def test_clear_retrieve_returns_empty(self) -> None:
        wm = make_wm()
        wm.encode("session task")
        wm.clear()
        assert wm.retrieve("task") == []

    def test_clear_then_encode_works(self) -> None:
        wm = make_wm()
        for i in range(5):
            wm.encode(f"item {i}")
        wm.clear()
        eid = wm.encode("fresh start")
        assert wm.size == 1
        assert wm.all_entries()[0].entry_id == eid

    def test_clear_does_not_change_capacity(self) -> None:
        wm = make_wm(capacity=8)
        wm.encode("test")
        wm.clear()
        assert wm.capacity == 8


# ---------------------------------------------------------------------------
# all_entries
# ---------------------------------------------------------------------------


class TestAllEntries:
    def test_all_entries_empty(self) -> None:
        assert make_wm().all_entries() == []

    def test_all_entries_returns_layer_entries(self) -> None:
        wm = make_wm()
        wm.encode("item")
        entries = wm.all_entries()
        assert all(isinstance(e, LayerEntry) for e in entries)

    def test_all_entries_oldest_first(self) -> None:
        wm = make_wm(capacity=5)
        for i in range(5):
            wm.encode(f"item {i}")
        contents = [e.content for e in wm.all_entries()]
        assert contents == [f"item {i}" for i in range(5)]

    def test_all_entries_does_not_mutate_internal_state(self) -> None:
        wm = make_wm(capacity=5)
        wm.encode("a")
        entries = wm.all_entries()
        entries.clear()
        assert wm.size == 1


# ---------------------------------------------------------------------------
# __len__ dunder
# ---------------------------------------------------------------------------


class TestLen:
    def test_len_matches_size(self) -> None:
        wm = make_wm(capacity=10)
        for i in range(6):
            wm.encode(f"item {i}")
        assert len(wm) == wm.size

    def test_len_empty(self) -> None:
        assert len(make_wm()) == 0

    def test_len_at_capacity(self) -> None:
        wm = make_wm(capacity=4)
        for i in range(4):
            wm.encode(f"item {i}")
        assert len(wm) == 4


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_overflow_many_times(self) -> None:
        cap = 7
        wm = make_wm(capacity=cap)
        all_ids: list[str] = []
        for i in range(100):
            eid = wm.encode(f"session event {i}")
            all_ids.append(eid)

        assert wm.size == cap
        present = {e.entry_id for e in wm.all_entries()}
        assert present == set(all_ids[-cap:])

    def test_encode_retrieve_cycle(self) -> None:
        wm = L1WorkingMemory(capacity=10)
        wm.encode("started reading config file")
        wm.encode("parsed Python source code")
        wm.encode("encountered syntax error in module")
        wm.encode("weather is sunny today")

        results = wm.retrieve("Python source code", top_k=5)
        top_content = [r.content for r in results]
        assert "parsed Python source code" in top_content
        assert results[0].content == "parsed Python source code"

    def test_l0_and_l1_are_independent(self) -> None:
        """L0 and L1 are independent; encoding into one does not affect the other."""
        from hm_arch.layers.l0_sensory import L0SensoryRegister

        l0 = L0SensoryRegister(capacity=5)
        l1 = L1WorkingMemory(capacity=5)

        l0.encode("event in L0")
        assert l1.size == 0

        l1.encode("task in L1")
        assert l0.size == 1

    def test_session_context_simulation(self) -> None:
        """Simulate an agent working session with bounded working memory."""
        wm = L1WorkingMemory(capacity=4)

        steps = [
            ("reading spec document", EventType.TASK),
            ("identified three requirements", EventType.OBSERVATION),
            ("decided on approach A", EventType.DECISION),
            ("wrote first function", EventType.CODE),
            ("found and fixed a bug", EventType.ERROR),  # evicts "reading spec document"
        ]
        for content, etype in steps:
            wm.encode(content, event_type=etype)

        assert wm.size == 4
        contents = [e.content for e in wm.all_entries()]
        assert "reading spec document" not in contents
        assert "found and fixed a bug" in contents

        results = wm.retrieve("bug fix", top_k=5)
        assert results[0].content == "found and fixed a bug"
