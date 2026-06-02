"""Tests for HMArch public facade (src/hm_arch/core.py).

Coverage
--------
Construction
* HMArch can be constructed with db_path=":memory:" (offline, no files).
* HMArch can be constructed with an explicit MemoryConfig.
* HMArch is exported from the top-level hm_arch package.

add()
* Returns a MemoryReceipt with a non-empty memory_id.
* Receipt layer is 2 (L2 is the durable layer).
* Receipt importance matches the supplied value.
* Receipt initial_strength is 1.0.
* Receipt decay_estimate is a non-empty dict.
* add() stores the item in L2 (count increases).
* add() stores the item in L1 (session snapshot grows).
* add() accepts all EventType variants without error.
* Metadata passed to add() is stored and retrievable.

search()
* Returns a SearchResult with a results list.
* Results are instances of MemoryItem.
* Results are sorted descending by score.
* search() on an empty store returns an empty results list.
* source_breakdown dict has integer layer keys.
* total_scanned equals the sum of source_breakdown values.
* timing_ms is a non-negative float.

Scoring
* score = retention * relevance * layer_priority for each item.
* Items with higher relevance rank above items with lower relevance.

CJK support
* memory.add("用户偏好 Python") can be found by memory.search("用户偏好").
* memory.add("用户偏好 Python", EventType.CONVERSATION) is found by
  memory.search("用户喜欢什么语言") (shared CJK character tokens).

Offline / persistence
* Reopening the same SQLite file preserves searchable memories.

Context manager
* HMArch works as a context manager; close() is called on __exit__.

Example execution
* examples/basic_usage.py runs without error.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

import hm_arch
from hm_arch import (
    ConsolidationReport,
    EventType,
    HMArch,
    MemoryConfig,
    MemoryItem,
    MemoryReceipt,
    RetentionCurve,
    SearchResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mem() -> HMArch:
    """Fresh in-memory HMArch instance for each test."""
    instance = HMArch(db_path=":memory:")
    yield instance
    instance.close()


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_hmarch_importable_from_package() -> None:
    assert hasattr(hm_arch, "HMArch")
    assert hm_arch.HMArch is HMArch


def test_hmarch_constructs_with_memory_db() -> None:
    m = HMArch(db_path=":memory:")
    m.close()


def test_hmarch_constructs_with_explicit_config() -> None:
    cfg = MemoryConfig(db_path=":memory:")
    m = HMArch(config=cfg)
    m.close()


def test_hmarch_in_all() -> None:
    assert "HMArch" in hm_arch.__all__


# ---------------------------------------------------------------------------
# add() — return value
# ---------------------------------------------------------------------------


def test_add_returns_memory_receipt(mem: HMArch) -> None:
    receipt = mem.add("Hello world")
    assert isinstance(receipt, MemoryReceipt)


def test_add_receipt_has_nonempty_memory_id(mem: HMArch) -> None:
    receipt = mem.add("Hello world")
    assert isinstance(receipt.memory_id, str)
    assert len(receipt.memory_id) > 0


def test_add_receipt_layer_is_2(mem: HMArch) -> None:
    receipt = mem.add("Hello world")
    assert receipt.layer == 2


def test_add_receipt_initial_strength_is_1(mem: HMArch) -> None:
    receipt = mem.add("Hello world")
    assert receipt.initial_strength == 1.0


def test_add_receipt_importance_reflects_supplied_value(mem: HMArch) -> None:
    receipt = mem.add("Hello world", importance=0.9)
    assert receipt.importance == pytest.approx(0.9)


def test_add_receipt_decay_estimate_nonempty(mem: HMArch) -> None:
    receipt = mem.add("Hello world")
    assert isinstance(receipt.decay_estimate, dict)
    assert len(receipt.decay_estimate) > 0


def test_add_receipt_default_importance_is_half(mem: HMArch) -> None:
    receipt = mem.add("Hello world")
    assert receipt.importance == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# add() — side effects
# ---------------------------------------------------------------------------


def test_add_increments_l2_count(mem: HMArch) -> None:
    assert mem._l2.count() == 0
    mem.add("First event")
    assert mem._l2.count() == 1
    mem.add("Second event")
    assert mem._l2.count() == 2


def test_add_increments_l1_size(mem: HMArch) -> None:
    assert mem._l1.size == 0
    mem.add("First event")
    assert mem._l1.size == 1


def test_add_all_event_types(mem: HMArch) -> None:
    for event_type in EventType:
        receipt = mem.add(f"event {event_type.value}", event_type=event_type)
        assert isinstance(receipt.memory_id, str)


def test_add_metadata_roundtrip(mem: HMArch) -> None:
    receipt = mem.add("Python event", metadata={"source": "test"})
    results = mem.search("Python event", top_k=1)
    assert len(results.results) > 0
    assert results.results[0].metadata.get("source") == "test"


# ---------------------------------------------------------------------------
# search() — basics
# ---------------------------------------------------------------------------


def test_search_returns_search_result(mem: HMArch) -> None:
    mem.add("Hello world")
    result = mem.search("Hello world")
    assert isinstance(result, SearchResult)


def test_search_results_are_memory_items(mem: HMArch) -> None:
    mem.add("Hello world")
    result = mem.search("Hello world")
    for item in result.results:
        assert isinstance(item, MemoryItem)


def test_search_empty_store_returns_empty(mem: HMArch) -> None:
    result = mem.search("anything")
    assert result.results == []


def test_search_respects_top_k(mem: HMArch) -> None:
    for i in range(10):
        mem.add(f"item number {i}")
    result = mem.search("item", top_k=3)
    assert len(result.results) <= 3


def test_search_source_breakdown_keys_are_ints(mem: HMArch) -> None:
    result = mem.search("anything")
    for k in result.source_breakdown:
        assert isinstance(k, int)


def test_search_total_scanned_equals_sum_of_breakdown(mem: HMArch) -> None:
    mem.add("foo bar")
    result = mem.search("foo")
    assert result.total_scanned == sum(result.source_breakdown.values())


def test_search_timing_ms_is_nonnegative(mem: HMArch) -> None:
    mem.add("foo bar")
    result = mem.search("foo")
    assert result.timing_ms >= 0.0


# ---------------------------------------------------------------------------
# search() — result structure
# ---------------------------------------------------------------------------


def test_search_result_has_layer_field(mem: HMArch) -> None:
    mem.add("Python is fun")
    result = mem.search("Python")
    assert len(result.results) > 0
    for item in result.results:
        assert hasattr(item, "layer")
        assert item.layer in (0, 1, 2, 3)


def test_search_result_has_score_field(mem: HMArch) -> None:
    mem.add("Python is fun")
    result = mem.search("Python")
    for item in result.results:
        assert hasattr(item, "score")
        assert isinstance(item.score, float)


def test_search_result_has_retention_field(mem: HMArch) -> None:
    mem.add("Python is fun")
    result = mem.search("Python")
    for item in result.results:
        assert hasattr(item, "retention")
        assert 0.0 <= item.retention <= 1.0


def test_search_result_has_relevance_field(mem: HMArch) -> None:
    mem.add("Python is fun")
    result = mem.search("Python")
    for item in result.results:
        assert hasattr(item, "relevance")
        assert 0.0 <= item.relevance <= 1.0


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_results_sorted_descending_by_score(mem: HMArch) -> None:
    for i in range(5):
        mem.add(f"memory item {i}")
    result = mem.search("memory item", top_k=5)
    scores = [item.score for item in result.results]
    assert scores == sorted(scores, reverse=True), (
        f"Results not sorted descending: {scores}"
    )


def test_score_equals_retention_times_relevance_times_priority(mem: HMArch) -> None:
    mem.add("Python development")
    result = mem.search("Python", top_k=5)
    assert len(result.results) > 0
    cfg = mem._config
    for item in result.results:
        layer_key = f"L{item.layer}"
        priority = cfg.layer_priorities.get(layer_key, 1.0)
        expected = item.retention * item.relevance * priority
        assert item.score == pytest.approx(expected, abs=1e-9), (
            f"score mismatch for layer {item.layer}: "
            f"{item.score} != {expected}"
        )


def test_more_relevant_item_ranks_above_less_relevant(mem: HMArch) -> None:
    mem.add("Python Python Python")
    mem.add("unrelated topic about databases")
    result = mem.search("Python", top_k=5)
    assert len(result.results) >= 2
    python_item = next((r for r in result.results if "Python" in r.content), None)
    unrelated_item = next(
        (r for r in result.results if "unrelated" in r.content), None
    )
    if python_item and unrelated_item:
        assert python_item.score >= unrelated_item.score


# ---------------------------------------------------------------------------
# CJK support
# ---------------------------------------------------------------------------


def test_cjk_add_found_by_cjk_query(mem: HMArch) -> None:
    """memory.add("用户偏好 Python") must be found by memory.search("用户偏好")."""
    mem.add("用户偏好 Python")
    result = mem.search("用户偏好", top_k=5)
    assert len(result.results) > 0
    contents = [item.content for item in result.results]
    assert any("用户偏好" in c for c in contents), (
        f"Expected CJK content in results, got: {contents}"
    )


def test_cjk_preference_found_by_language_query(mem: HMArch) -> None:
    """Acceptance criterion: add("用户偏好 Python") found by search("用户喜欢什么语言")."""
    mem.add("用户偏好 Python", event_type=EventType.CONVERSATION)
    result = mem.search("用户喜欢什么语言", top_k=5)
    # The query and content share CJK tokens "用" and "户"; score must be > 0.
    assert len(result.results) > 0
    assert result.results[0].score > 0, (
        "Top result should have a positive score for shared CJK tokens"
    )


def test_cjk_result_has_positive_score(mem: HMArch) -> None:
    mem.add("用户偏好 Python", event_type=EventType.CONVERSATION)
    result = mem.search("用户喜欢什么语言", top_k=5)
    scores = [item.score for item in result.results]
    assert any(s > 0 for s in scores), f"All scores zero: {scores}"


# ---------------------------------------------------------------------------
# Persistence (offline)
# ---------------------------------------------------------------------------


def test_reopening_db_preserves_memories() -> None:
    """Memories added in one HMArch instance survive a close/reopen cycle."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = str(Path(tmpdir) / "test.db")

        m1 = HMArch(db_path=db_file)
        m1.add("Python is a great language")
        m1.close()

        m2 = HMArch(db_path=db_file)
        result = m2.search("Python language", top_k=5)
        m2.close()

    assert len(result.results) > 0, (
        "Memories should survive close/reopen; got empty results"
    )


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


def test_context_manager_closes_db() -> None:
    with HMArch(db_path=":memory:") as m:
        m.add("test")
        assert m._db.is_connected
    assert not m._db.is_connected


# ---------------------------------------------------------------------------
# consolidate()
# ---------------------------------------------------------------------------


def test_consolidate_returns_report(mem: HMArch) -> None:
    mem.add("User prefers Python", event_type=EventType.CONVERSATION)
    report = mem.consolidate()
    assert isinstance(report, ConsolidationReport)


def test_consolidate_extracts_preference_semantics(mem: HMArch) -> None:
    mem.add("User prefers Python", event_type=EventType.CONVERSATION, importance=0.9)
    report = mem.consolidate()
    assert report.extracted_semantics >= 1


def test_consolidate_updates_last_consolidation_at(mem: HMArch) -> None:
    mem.add("Some episodic fact")
    assert mem.get_stats().last_consolidation_at is None
    mem.consolidate()
    assert mem.get_stats().last_consolidation_at is not None


# ---------------------------------------------------------------------------
# get_retention_curve()
# ---------------------------------------------------------------------------


def test_get_retention_curve_l2(mem: HMArch) -> None:
    curve = mem.get_retention_curve(layer=2)
    assert isinstance(curve, RetentionCurve)
    assert len(curve.days) == len(curve.retention)
    assert 30 in curve.days
    day30 = curve.retention[curve.days.index(30)]
    assert day30 == pytest.approx(0.26, abs=0.02)


def test_get_retention_curve_l3(mem: HMArch) -> None:
    curve = mem.get_retention_curve(layer=3)
    day30 = curve.retention[curve.days.index(30)]
    assert day30 == pytest.approx(0.63, abs=0.05)


def test_get_retention_curve_invalid_layer_raises(mem: HMArch) -> None:
    with pytest.raises(ValueError, match="layer 2 or 3"):
        mem.get_retention_curve(layer=1)


# ---------------------------------------------------------------------------
# Example execution
# ---------------------------------------------------------------------------


def test_basic_usage_example_runs() -> None:
    """examples/basic_usage.py must run without error (offline)."""
    examples_dir = Path(__file__).parent.parent / "examples"
    script = examples_dir / "basic_usage.py"
    assert script.exists(), f"Example script not found: {script}"

    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"basic_usage.py exited with {result.returncode}:\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert "completed successfully" in result.stdout
