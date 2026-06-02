"""Tests for L0SensoryRegister.

Coverage:
* Basic add / snapshot / retrieve / clear lifecycle.
* Bounded window: capacity is respected.
* Overflow eviction: oldest item is dropped first (FIFO).
* memory_id is unique and returned correctly.
* Layer index is 0.
* metadata is stored and returned.
* retrieve returns items sorted by relevance (token overlap).
* retrieve respects top_k.
* Empty layer edge cases.
* Invalid capacity raises ValueError.
"""

from __future__ import annotations

import pytest

from hm_arch.layers import L0SensoryRegister, LayerItem


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def reg3() -> L0SensoryRegister:
    """A register with capacity 3."""
    return L0SensoryRegister(capacity=3)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_default_capacity() -> None:
    reg = L0SensoryRegister()
    assert reg.capacity == 7


def test_custom_capacity() -> None:
    reg = L0SensoryRegister(capacity=10)
    assert reg.capacity == 10


def test_invalid_capacity_raises() -> None:
    with pytest.raises(ValueError):
        L0SensoryRegister(capacity=0)

    with pytest.raises(ValueError):
        L0SensoryRegister(capacity=-1)


# ---------------------------------------------------------------------------
# Layer index
# ---------------------------------------------------------------------------


def test_layer_index_is_zero() -> None:
    assert L0SensoryRegister.LAYER_INDEX == 0
    assert L0SensoryRegister().LAYER_INDEX == 0


# ---------------------------------------------------------------------------
# Basic add / size / snapshot
# ---------------------------------------------------------------------------


def test_empty_on_creation(reg3: L0SensoryRegister) -> None:
    assert reg3.size == 0
    assert reg3.snapshot() == []


def test_add_returns_string_id(reg3: L0SensoryRegister) -> None:
    mid = reg3.add("hello")
    assert isinstance(mid, str)
    assert len(mid) > 0


def test_add_increases_size(reg3: L0SensoryRegister) -> None:
    reg3.add("a")
    assert reg3.size == 1
    reg3.add("b")
    assert reg3.size == 2


def test_size_does_not_exceed_capacity(reg3: L0SensoryRegister) -> None:
    for i in range(10):
        reg3.add(f"item {i}")
    assert reg3.size == 3


def test_snapshot_returns_list_of_layer_items(reg3: L0SensoryRegister) -> None:
    reg3.add("alpha")
    items = reg3.snapshot()
    assert isinstance(items, list)
    assert all(isinstance(it, LayerItem) for it in items)


def test_snapshot_order_oldest_to_newest(reg3: L0SensoryRegister) -> None:
    reg3.add("first")
    reg3.add("second")
    reg3.add("third")
    contents = [it.content for it in reg3.snapshot()]
    assert contents == ["first", "second", "third"]


def test_snapshot_is_shallow_copy(reg3: L0SensoryRegister) -> None:
    reg3.add("x")
    snap1 = reg3.snapshot()
    snap1.clear()
    assert reg3.size == 1, "Mutating snapshot must not affect the register"


# ---------------------------------------------------------------------------
# memory_id uniqueness and item fields
# ---------------------------------------------------------------------------


def test_memory_ids_are_unique(reg3: L0SensoryRegister) -> None:
    ids = {reg3.add(f"item {i}") for i in range(3)}
    assert len(ids) == 3


def test_item_layer_is_zero(reg3: L0SensoryRegister) -> None:
    mid = reg3.add("test")
    item = reg3.snapshot()[0]
    assert item.layer == 0
    assert item.memory_id == mid


def test_item_content_stored(reg3: L0SensoryRegister) -> None:
    reg3.add("hello world")
    item = reg3.snapshot()[0]
    assert item.content == "hello world"


def test_item_metadata_stored(reg3: L0SensoryRegister) -> None:
    reg3.add("test", metadata={"source": "unit_test", "priority": 1})
    item = reg3.snapshot()[0]
    assert item.metadata == {"source": "unit_test", "priority": 1}


def test_item_metadata_defaults_to_empty_dict(reg3: L0SensoryRegister) -> None:
    reg3.add("test")
    item = reg3.snapshot()[0]
    assert item.metadata == {}


def test_item_metadata_is_copy(reg3: L0SensoryRegister) -> None:
    original = {"key": "value"}
    reg3.add("test", metadata=original)
    original["key"] = "mutated"
    item = reg3.snapshot()[0]
    assert item.metadata["key"] == "value", "Layer must store a copy of metadata"


def test_item_added_at_is_set(reg3: L0SensoryRegister) -> None:
    reg3.add("test")
    item = reg3.snapshot()[0]
    assert item.added_at is not None


# ---------------------------------------------------------------------------
# Overflow / eviction behaviour
# ---------------------------------------------------------------------------


def test_overflow_evicts_oldest(reg3: L0SensoryRegister) -> None:
    """Adding beyond capacity must drop the oldest item."""
    reg3.add("oldest")
    reg3.add("middle")
    reg3.add("newest")
    # Window is now full: [oldest, middle, newest]
    reg3.add("extra")
    # "oldest" should be gone; "extra" should be present.
    contents = {it.content for it in reg3.snapshot()}
    assert "oldest" not in contents
    assert "extra" in contents


def test_overflow_keeps_correct_count(reg3: L0SensoryRegister) -> None:
    for i in range(20):
        reg3.add(f"item {i}")
    assert reg3.size == 3


def test_overflow_fifo_order_preserved() -> None:
    """After several overflows the window must still be oldest-to-newest."""
    reg = L0SensoryRegister(capacity=3)
    for i in range(7):
        reg.add(f"item {i}")
    # Last 3 added: item 4, item 5, item 6
    contents = [it.content for it in reg.snapshot()]
    assert contents == ["item 4", "item 5", "item 6"]


def test_single_capacity_always_holds_last_item() -> None:
    reg = L0SensoryRegister(capacity=1)
    reg.add("first")
    reg.add("second")
    assert reg.size == 1
    assert reg.snapshot()[0].content == "second"


# ---------------------------------------------------------------------------
# Retrieve
# ---------------------------------------------------------------------------


def test_retrieve_empty_returns_empty(reg3: L0SensoryRegister) -> None:
    assert reg3.retrieve("query") == []


def test_retrieve_returns_layer_items(reg3: L0SensoryRegister) -> None:
    reg3.add("Python is great")
    results = reg3.retrieve("Python", top_k=5)
    assert all(isinstance(r, LayerItem) for r in results)


def test_retrieve_respects_top_k() -> None:
    reg = L0SensoryRegister(capacity=7)
    for i in range(5):
        reg.add(f"Python topic {i}")
    results = reg.retrieve("Python", top_k=3)
    assert len(results) <= 3


def test_retrieve_most_relevant_first() -> None:
    reg = L0SensoryRegister(capacity=7)
    reg.add("Python is a programming language")
    reg.add("Java is used for enterprise apps")
    reg.add("Python data science machine learning")
    results = reg.retrieve("Python data science", top_k=3)
    # The item with more Python/data/science tokens should rank first.
    assert results[0].content == "Python data science machine learning"


def test_retrieve_top_k_larger_than_size() -> None:
    reg = L0SensoryRegister(capacity=7)
    reg.add("item one")
    results = reg.retrieve("item", top_k=100)
    assert len(results) == 1


# ---------------------------------------------------------------------------
# Clear
# ---------------------------------------------------------------------------


def test_clear_empties_register(reg3: L0SensoryRegister) -> None:
    reg3.add("a")
    reg3.add("b")
    reg3.clear()
    assert reg3.size == 0
    assert reg3.snapshot() == []


def test_can_add_after_clear(reg3: L0SensoryRegister) -> None:
    reg3.add("before clear")
    reg3.clear()
    mid = reg3.add("after clear")
    assert reg3.size == 1
    assert reg3.snapshot()[0].memory_id == mid


# ---------------------------------------------------------------------------
# Import path
# ---------------------------------------------------------------------------


def test_importable_from_layers_package() -> None:
    from hm_arch.layers import L0SensoryRegister as L0  # noqa: F401

    assert L0 is not None
