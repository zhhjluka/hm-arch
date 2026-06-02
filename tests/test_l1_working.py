"""Tests for L1WorkingMemory.

Coverage:
* Basic add / snapshot / retrieve / clear lifecycle.
* Bounded store: capacity is respected.
* Overflow eviction: oldest item is dropped first (FIFO).
* memory_id is unique and returned correctly.
* Layer index is 1.
* metadata is stored and returned.
* retrieve returns items sorted by relevance (token overlap).
* retrieve respects top_k.
* Empty store edge cases.
* Invalid capacity raises ValueError.
* L1 capacity defaults and limits differ from L0.
"""

from __future__ import annotations

import pytest

from hm_arch.layers import L1WorkingMemory, LayerItem


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def wm5() -> L1WorkingMemory:
    """Working memory with capacity 5."""
    return L1WorkingMemory(capacity=5)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_default_capacity() -> None:
    wm = L1WorkingMemory()
    assert wm.capacity == 50


def test_custom_capacity() -> None:
    wm = L1WorkingMemory(capacity=100)
    assert wm.capacity == 100


def test_invalid_capacity_raises() -> None:
    with pytest.raises(ValueError):
        L1WorkingMemory(capacity=0)

    with pytest.raises(ValueError):
        L1WorkingMemory(capacity=-5)


# ---------------------------------------------------------------------------
# Layer index
# ---------------------------------------------------------------------------


def test_layer_index_is_one() -> None:
    assert L1WorkingMemory.LAYER_INDEX == 1
    assert L1WorkingMemory().LAYER_INDEX == 1


# ---------------------------------------------------------------------------
# Basic add / size / snapshot
# ---------------------------------------------------------------------------


def test_empty_on_creation(wm5: L1WorkingMemory) -> None:
    assert wm5.size == 0
    assert wm5.snapshot() == []


def test_add_returns_string_id(wm5: L1WorkingMemory) -> None:
    mid = wm5.add("hello")
    assert isinstance(mid, str)
    assert len(mid) > 0


def test_add_increases_size(wm5: L1WorkingMemory) -> None:
    wm5.add("a")
    assert wm5.size == 1
    wm5.add("b")
    assert wm5.size == 2


def test_size_does_not_exceed_capacity(wm5: L1WorkingMemory) -> None:
    for i in range(20):
        wm5.add(f"item {i}")
    assert wm5.size == 5


def test_snapshot_returns_list_of_layer_items(wm5: L1WorkingMemory) -> None:
    wm5.add("alpha")
    items = wm5.snapshot()
    assert isinstance(items, list)
    assert all(isinstance(it, LayerItem) for it in items)


def test_snapshot_order_oldest_to_newest(wm5: L1WorkingMemory) -> None:
    wm5.add("first")
    wm5.add("second")
    wm5.add("third")
    contents = [it.content for it in wm5.snapshot()]
    assert contents == ["first", "second", "third"]


def test_snapshot_is_shallow_copy(wm5: L1WorkingMemory) -> None:
    wm5.add("x")
    snap1 = wm5.snapshot()
    snap1.clear()
    assert wm5.size == 1, "Mutating snapshot must not affect the store"


# ---------------------------------------------------------------------------
# memory_id uniqueness and item fields
# ---------------------------------------------------------------------------


def test_memory_ids_are_unique(wm5: L1WorkingMemory) -> None:
    ids = {wm5.add(f"item {i}") for i in range(5)}
    assert len(ids) == 5


def test_item_layer_is_one(wm5: L1WorkingMemory) -> None:
    mid = wm5.add("test")
    item = wm5.snapshot()[0]
    assert item.layer == 1
    assert item.memory_id == mid


def test_item_content_stored(wm5: L1WorkingMemory) -> None:
    wm5.add("hello world")
    item = wm5.snapshot()[0]
    assert item.content == "hello world"


def test_item_metadata_stored(wm5: L1WorkingMemory) -> None:
    wm5.add("test", metadata={"event": "click", "count": 3})
    item = wm5.snapshot()[0]
    assert item.metadata == {"event": "click", "count": 3}


def test_item_metadata_defaults_to_empty_dict(wm5: L1WorkingMemory) -> None:
    wm5.add("test")
    item = wm5.snapshot()[0]
    assert item.metadata == {}


def test_item_metadata_is_copy(wm5: L1WorkingMemory) -> None:
    original = {"key": "value"}
    wm5.add("test", metadata=original)
    original["key"] = "mutated"
    item = wm5.snapshot()[0]
    assert item.metadata["key"] == "value", "Layer must store a copy of metadata"


def test_item_added_at_is_set(wm5: L1WorkingMemory) -> None:
    wm5.add("test")
    item = wm5.snapshot()[0]
    assert item.added_at is not None


# ---------------------------------------------------------------------------
# Overflow / eviction behaviour
# ---------------------------------------------------------------------------


def test_overflow_evicts_oldest(wm5: L1WorkingMemory) -> None:
    """Adding beyond capacity must drop the oldest item."""
    wm5.add("oldest")
    wm5.add("second")
    wm5.add("third")
    wm5.add("fourth")
    wm5.add("fifth")
    # Store is full at capacity 5.
    wm5.add("extra")
    contents = {it.content for it in wm5.snapshot()}
    assert "oldest" not in contents
    assert "extra" in contents


def test_overflow_keeps_correct_count(wm5: L1WorkingMemory) -> None:
    for i in range(50):
        wm5.add(f"item {i}")
    assert wm5.size == 5


def test_overflow_fifo_order_preserved() -> None:
    """After several overflows the window must still be oldest-to-newest."""
    wm = L1WorkingMemory(capacity=4)
    for i in range(9):
        wm.add(f"item {i}")
    # Last 4 added: item 5, item 6, item 7, item 8
    contents = [it.content for it in wm.snapshot()]
    assert contents == ["item 5", "item 6", "item 7", "item 8"]


def test_single_capacity_always_holds_last_item() -> None:
    wm = L1WorkingMemory(capacity=1)
    wm.add("first")
    wm.add("second")
    assert wm.size == 1
    assert wm.snapshot()[0].content == "second"


def test_large_capacity_retains_all_within_bound() -> None:
    wm = L1WorkingMemory(capacity=50)
    for i in range(50):
        wm.add(f"item {i}")
    assert wm.size == 50
    wm.add("one more")
    assert wm.size == 50
    assert wm.snapshot()[0].content == "item 1"


# ---------------------------------------------------------------------------
# Retrieve
# ---------------------------------------------------------------------------


def test_retrieve_empty_returns_empty(wm5: L1WorkingMemory) -> None:
    assert wm5.retrieve("query") == []


def test_retrieve_returns_layer_items(wm5: L1WorkingMemory) -> None:
    wm5.add("Python is great")
    results = wm5.retrieve("Python", top_k=5)
    assert all(isinstance(r, LayerItem) for r in results)


def test_retrieve_respects_top_k() -> None:
    wm = L1WorkingMemory(capacity=20)
    for i in range(10):
        wm.add(f"Python item {i}")
    results = wm.retrieve("Python", top_k=4)
    assert len(results) <= 4


def test_retrieve_most_relevant_first() -> None:
    wm = L1WorkingMemory(capacity=10)
    wm.add("Java enterprise backend")
    wm.add("Python quick scripting")
    wm.add("Python machine learning deep learning")
    results = wm.retrieve("Python machine learning", top_k=3)
    assert results[0].content == "Python machine learning deep learning"


def test_retrieve_top_k_larger_than_size() -> None:
    wm = L1WorkingMemory(capacity=10)
    wm.add("item one")
    results = wm.retrieve("item", top_k=100)
    assert len(results) == 1


def test_retrieve_result_layer_is_one() -> None:
    wm = L1WorkingMemory(capacity=5)
    wm.add("working memory item")
    results = wm.retrieve("working memory", top_k=1)
    assert len(results) == 1
    assert results[0].layer == 1


# ---------------------------------------------------------------------------
# Clear
# ---------------------------------------------------------------------------


def test_clear_empties_store(wm5: L1WorkingMemory) -> None:
    wm5.add("a")
    wm5.add("b")
    wm5.clear()
    assert wm5.size == 0
    assert wm5.snapshot() == []


def test_can_add_after_clear(wm5: L1WorkingMemory) -> None:
    wm5.add("before clear")
    wm5.clear()
    mid = wm5.add("after clear")
    assert wm5.size == 1
    assert wm5.snapshot()[0].memory_id == mid


# ---------------------------------------------------------------------------
# L0 vs L1 isolation
# ---------------------------------------------------------------------------


def test_l0_and_l1_are_independent() -> None:
    """Items added to L1 must not appear in L0 and vice versa."""
    from hm_arch.layers import L0SensoryRegister

    l0 = L0SensoryRegister(capacity=5)
    l1 = L1WorkingMemory(capacity=5)

    l0.add("sensor event")
    l1.add("working memory event")

    assert l0.size == 1
    assert l1.size == 1
    assert l0.snapshot()[0].content == "sensor event"
    assert l1.snapshot()[0].content == "working memory event"


# ---------------------------------------------------------------------------
# Import path
# ---------------------------------------------------------------------------


def test_importable_from_layers_package() -> None:
    from hm_arch.layers import L1WorkingMemory as L1  # noqa: F401

    assert L1 is not None
