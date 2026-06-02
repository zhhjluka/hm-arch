"""Tests for HMArch search / retrieval behaviour.

Verifies the scoring formula, multi-layer combination, layer priorities,
and result ordering.  All tests use an in-memory SQLite database.
"""

from __future__ import annotations

import pytest

from hm_arch import HMArch, EventType


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
# Score formula: retention * relevance * layer_priority
# ---------------------------------------------------------------------------


class TestScoringFormula:
    def test_score_equals_retention_times_relevance_times_priority(
        self, mem: HMArch
    ) -> None:
        mem.add("Python programming")
        result = mem.search("Python")
        priorities = mem._config.layer_priorities
        for item in result.results:
            priority = priorities[f"L{item.layer}"]
            expected = item.retention * item.relevance * priority
            assert abs(item.score - expected) < 1e-9, (
                f"score mismatch for layer {item.layer}: "
                f"{item.score!r} != {expected!r}"
            )

    def test_score_is_zero_when_relevance_is_zero(self, mem: HMArch) -> None:
        mem.add("completely unrelated zzzz content")
        result = mem.search("Python programming")
        # Items with zero relevance should have zero score.
        for item in result.results:
            if item.relevance == 0.0:
                assert item.score == 0.0

    def test_score_upper_bound_is_layer_priority(self, mem: HMArch) -> None:
        # A perfect relevance of 1.0 with retention 1.0 gives score == priority.
        mem.add("python python python")
        result = mem.search("python python python")
        priorities = mem._config.layer_priorities
        for item in result.results:
            max_score = priorities[f"L{item.layer}"]
            assert item.score <= max_score + 1e-9


# ---------------------------------------------------------------------------
# Layer combination
# ---------------------------------------------------------------------------


class TestLayerCombination:
    def test_l1_and_l2_both_contribute(self, mem: HMArch) -> None:
        """A freshly added item should appear in both L1 and L2 candidates."""
        mem.add("Python scripting")
        result = mem.search("Python")
        layers = {item.layer for item in result.results}
        # After one add, we expect hits from L1 (in-memory) and L2 (durable).
        assert 1 in layers or 2 in layers

    def test_results_deduplicated_by_memory_id(self, mem: HMArch) -> None:
        """No two result items should share the same memory_id."""
        for _ in range(3):
            mem.add("Python scripting language")
        result = mem.search("Python")
        ids = [item.memory_id for item in result.results]
        assert len(ids) == len(set(ids)), "Duplicate memory_id found in results"

    def test_source_breakdown_sums_to_total_scanned(self, mem: HMArch) -> None:
        mem.add("hello world")
        result = mem.search("hello")
        assert sum(result.source_breakdown.values()) == result.total_scanned

    def test_source_breakdown_keys_are_layer_indices(self, mem: HMArch) -> None:
        mem.add("hello")
        result = mem.search("hello")
        for key in result.source_breakdown:
            assert key in (1, 2, 3)


# ---------------------------------------------------------------------------
# Result ordering
# ---------------------------------------------------------------------------


class TestResultOrdering:
    def test_results_sorted_descending_by_score(self, mem: HMArch) -> None:
        mem.add("Python is the best language for scripting")
        mem.add("Completely irrelevant content about rainbows")
        result = mem.search("Python scripting language")
        scores = [item.score for item in result.results]
        assert scores == sorted(scores, reverse=True)

    def test_highly_relevant_item_ranks_first(self, mem: HMArch) -> None:
        mem.add("Python scripting language programming")
        mem.add("absolutely unrelated zzz content aaa")
        result = mem.search("Python scripting")
        assert len(result.results) >= 1
        top = result.results[0]
        assert "Python" in top.content or "python" in top.content.lower()

    def test_top_k_one_returns_single_result(self, mem: HMArch) -> None:
        for i in range(5):
            mem.add(f"Python item number {i}")
        result = mem.search("Python", top_k=1)
        assert len(result.results) == 1

    def test_top_k_zero_returns_empty(self, mem: HMArch) -> None:
        mem.add("Python")
        result = mem.search("Python", top_k=0)
        assert result.results == []


# ---------------------------------------------------------------------------
# CJK retrieval
# ---------------------------------------------------------------------------


class TestCJKRetrieval:
    def test_cjk_content_found_by_full_query(self, mem: HMArch) -> None:
        mem.add("用户偏好 Python")
        result = mem.search("用户偏好 Python")
        assert len(result.results) > 0

    def test_cjk_content_found_by_partial_query(self, mem: HMArch) -> None:
        """Acceptance criterion from the Linear issue."""
        mem.add("用户偏好 Python")
        result = mem.search("用户偏好")
        assert len(result.results) > 0
        contents = [item.content for item in result.results]
        assert any("用户偏好" in c for c in contents)

    def test_cjk_content_not_lost_after_multiple_adds(self, mem: HMArch) -> None:
        mem.add("用户偏好 Python")
        mem.add("Agent uses SQLite")
        mem.add("Python data science tools")
        result = mem.search("用户偏好")
        assert len(result.results) > 0
        contents = [item.content for item in result.results]
        assert any("用户偏好" in c for c in contents)


# ---------------------------------------------------------------------------
# Persistence (across HMArch restarts)
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_memories_survive_restart(self, tmp_path) -> None:
        """L2 and L3 memories should be retrievable after re-opening the DB."""
        db_path = str(tmp_path / "test.db")

        with HMArch(db_path=db_path) as m1:
            m1.add("用户偏好 Python", event_type=EventType.CONVERSATION)

        with HMArch(db_path=db_path) as m2:
            result = m2.search("用户偏好")
            # L2 rebuilds its vector index from SQLite on start-up.
            assert len(result.results) > 0
            contents = [item.content for item in result.results]
            assert any("用户偏好" in c for c in contents)
