"""Tests for L3 semantic memory layer.

Covers:
* Basic upsert and search (acceptance criteria from HM-7).
* Idempotent same-value upsert.
* Conflict detection: older memory marked ``superseded``.
* Latest active value ranks first in search results.
* Point-lookup via ``get()``.
* Active count accuracy via ``count()``.
* Vector-index rebuild on simulated process restart.

Test command: pytest tests/test_l3_semantic.py
"""

from __future__ import annotations

import pytest

from hm_arch.storage.sqlite import SQLiteStore
from hm_arch.layers.l3_semantic import L3SemanticMemory, SemanticItem


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    """In-memory SQLite store, connected and schema-initialised."""
    store = SQLiteStore(":memory:").connect()
    store.initialize_schema()
    yield store
    store.close()


@pytest.fixture()
def l3(db):
    """Fresh L3SemanticMemory backed by the in-memory SQLite store."""
    return L3SemanticMemory(db)


# ---------------------------------------------------------------------------
# Basic upsert and search — HM-7 acceptance criteria
# ---------------------------------------------------------------------------


class TestUpsertAndSearch:
    def test_upsert_returns_memory_id(self, l3):
        mid = l3.upsert("user", "likes", "Python")
        assert isinstance(mid, str)
        assert len(mid) == 32  # UUID4 hex

    def test_upsert_creates_searchable_triple(self, l3):
        """upsert('user', 'likes', 'Python') is searchable — acceptance criterion."""
        l3.upsert("user", "likes", "Python")
        results = l3.search("user likes Python")
        assert len(results) >= 1
        first = results[0]
        assert first.entity == "user"
        assert first.relation == "likes"
        assert first.value == "Python"

    def test_upsert_findable_by_entity_token(self, l3):
        l3.upsert("user", "likes", "Python")
        results = l3.search("user")
        assert any(r.entity == "user" for r in results)

    def test_upsert_findable_by_value_token(self, l3):
        l3.upsert("user", "likes", "Python")
        results = l3.search("Python")
        assert any(r.value == "Python" for r in results)

    def test_upsert_findable_by_relation_token(self, l3):
        l3.upsert("user", "likes", "Python")
        results = l3.search("likes")
        assert any(r.relation == "likes" for r in results)

    def test_search_returns_semantic_items(self, l3):
        l3.upsert("user", "likes", "Python")
        results = l3.search("Python")
        assert all(isinstance(r, SemanticItem) for r in results)

    def test_search_empty_store_returns_empty_list(self, l3):
        assert l3.search("anything") == []

    def test_search_top_k_limits_results(self, l3):
        for i in range(10):
            l3.upsert(f"entity{i}", "has", f"value{i}")
        results = l3.search("entity has value", top_k=3)
        assert len(results) <= 3

    def test_search_relevance_in_unit_interval(self, l3):
        l3.upsert("user", "likes", "Python")
        for r in l3.search("Python"):
            assert 0.0 <= r.relevance <= 1.0

    def test_search_layer_is_three(self, l3):
        l3.upsert("user", "likes", "Python")
        results = l3.search("Python")
        assert all(r.layer == 3 for r in results)


# ---------------------------------------------------------------------------
# Idempotent upsert (same value)
# ---------------------------------------------------------------------------


class TestIdempotentUpsert:
    def test_same_value_returns_same_memory_id(self, l3):
        mid1 = l3.upsert("user", "likes", "Python")
        mid2 = l3.upsert("user", "likes", "Python")
        assert mid1 == mid2

    def test_same_value_does_not_duplicate_row(self, l3):
        l3.upsert("user", "likes", "Python")
        l3.upsert("user", "likes", "Python")
        assert l3.count() == 1

    def test_same_value_version_stays_at_one(self, l3):
        l3.upsert("user", "likes", "Python")
        l3.upsert("user", "likes", "Python")
        item = l3.get("user", "likes")
        assert item is not None
        assert item.version == 1


# ---------------------------------------------------------------------------
# Conflict detection and supersession — HM-7 acceptance criteria
# ---------------------------------------------------------------------------


class TestConflictAndSupersession:
    def test_conflicting_value_marks_older_superseded(self, db, l3):
        """Conflicting value marks older memory as superseded — acceptance criterion."""
        old_mid = l3.upsert("user", "likes", "Python")
        l3.upsert("user", "likes", "Rust")

        rows = db.query(
            "SELECT status FROM memory_index WHERE id = ?", (old_mid,)
        )
        assert rows[0]["status"] == "superseded"

    def test_conflicting_value_new_triple_is_active(self, db, l3):
        l3.upsert("user", "likes", "Python")
        new_mid = l3.upsert("user", "likes", "Rust")

        rows = db.query(
            "SELECT status FROM memory_index WHERE id = ?", (new_mid,)
        )
        assert rows[0]["status"] == "active"

    def test_conflicting_value_superseded_by_points_to_new(self, db, l3):
        old_mid = l3.upsert("user", "likes", "Python")
        new_mid = l3.upsert("user", "likes", "Rust")

        rows = db.query(
            "SELECT superseded_by FROM memory_index WHERE id = ?", (old_mid,)
        )
        assert rows[0]["superseded_by"] == new_mid

    def test_conflicting_value_active_count_stays_at_one(self, l3):
        l3.upsert("user", "likes", "Python")
        l3.upsert("user", "likes", "Rust")
        assert l3.count() == 1

    def test_conflicting_value_version_increments(self, l3):
        l3.upsert("user", "likes", "Python")
        l3.upsert("user", "likes", "Rust")
        item = l3.get("user", "likes")
        assert item is not None
        assert item.version == 2

    def test_multiple_conflicts_chain_versions(self, l3):
        l3.upsert("user", "likes", "Python")
        l3.upsert("user", "likes", "Rust")
        l3.upsert("user", "likes", "Go")
        item = l3.get("user", "likes")
        assert item is not None
        assert item.value == "Go"
        assert item.version == 3

    def test_multiple_conflicts_only_latest_active(self, db, l3):
        l3.upsert("user", "likes", "Python")
        l3.upsert("user", "likes", "Rust")
        l3.upsert("user", "likes", "Go")
        rows = db.query(
            "SELECT COUNT(*) FROM memory_index WHERE layer = 3 AND status = 'active'"
        )
        assert rows[0][0] == 1

    def test_different_relations_are_independent(self, l3):
        l3.upsert("user", "likes", "Python")
        l3.upsert("user", "dislikes", "Java")
        assert l3.count() == 2
        assert l3.get("user", "likes") is not None
        assert l3.get("user", "dislikes") is not None

    def test_different_entities_are_independent(self, l3):
        l3.upsert("user", "likes", "Python")
        l3.upsert("agent", "likes", "Rust")
        assert l3.count() == 2


# ---------------------------------------------------------------------------
# Search ranking — latest active value ranks first
# ---------------------------------------------------------------------------


class TestSearchRanking:
    def test_latest_active_value_ranks_first(self, l3):
        """Latest active value ranks first — acceptance criterion."""
        l3.upsert("user", "likes", "Python")
        l3.upsert("user", "likes", "Rust")
        results = l3.search("user likes")
        assert len(results) >= 1
        assert results[0].value == "Rust"

    def test_superseded_value_not_in_search_results(self, l3):
        l3.upsert("user", "likes", "Python")
        l3.upsert("user", "likes", "Rust")
        # Search with both old and new tokens to maximise recall.
        results = l3.search("user likes Python Rust")
        values = [r.value for r in results]
        assert "Rust" in values
        assert "Python" not in values

    def test_only_active_rows_returned(self, db, l3):
        """search() must never surface superseded rows."""
        l3.upsert("user", "likes", "Python")
        l3.upsert("user", "likes", "Rust")
        results = l3.search("user likes Python Rust")
        for r in results:
            rows = db.query(
                "SELECT status FROM memory_index WHERE id = ?", (r.memory_id,)
            )
            assert rows[0]["status"] == "active"


# ---------------------------------------------------------------------------
# Point-lookup via get()
# ---------------------------------------------------------------------------


class TestGet:
    def test_get_returns_correct_triple(self, l3):
        l3.upsert("user", "likes", "Python")
        item = l3.get("user", "likes")
        assert item is not None
        assert item.entity == "user"
        assert item.relation == "likes"
        assert item.value == "Python"
        assert item.layer == 3

    def test_get_returns_none_for_unknown_entity(self, l3):
        assert l3.get("ghost", "likes") is None

    def test_get_returns_none_for_unknown_relation(self, l3):
        l3.upsert("user", "likes", "Python")
        assert l3.get("user", "hates") is None

    def test_get_returns_latest_after_conflict(self, l3):
        l3.upsert("user", "likes", "Python")
        l3.upsert("user", "likes", "Rust")
        item = l3.get("user", "likes")
        assert item is not None
        assert item.value == "Rust"

    def test_get_confidence_matches_upsert(self, l3):
        l3.upsert("user", "likes", "Python", confidence=0.85)
        item = l3.get("user", "likes")
        assert item is not None
        assert item.confidence == pytest.approx(0.85)

    def test_get_metadata_matches_upsert(self, l3):
        l3.upsert("user", "likes", "Python", metadata={"source": "test"})
        item = l3.get("user", "likes")
        assert item is not None
        assert item.metadata == {"source": "test"}

    def test_get_version_one_on_first_insert(self, l3):
        l3.upsert("user", "likes", "Python")
        item = l3.get("user", "likes")
        assert item is not None
        assert item.version == 1


# ---------------------------------------------------------------------------
# Count accuracy
# ---------------------------------------------------------------------------


class TestCount:
    def test_count_zero_on_empty_store(self, l3):
        assert l3.count() == 0

    def test_count_one_after_single_insert(self, l3):
        l3.upsert("user", "likes", "Python")
        assert l3.count() == 1

    def test_count_stable_after_same_value_upsert(self, l3):
        l3.upsert("user", "likes", "Python")
        l3.upsert("user", "likes", "Python")
        assert l3.count() == 1

    def test_count_stable_after_conflict(self, l3):
        l3.upsert("user", "likes", "Python")
        l3.upsert("user", "likes", "Rust")
        assert l3.count() == 1

    def test_count_multiple_independent_triples(self, l3):
        l3.upsert("user", "likes", "Python")
        l3.upsert("user", "dislikes", "Java")
        l3.upsert("agent", "uses", "SQLite")
        assert l3.count() == 3


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_confidence_above_one_raises(self, l3):
        with pytest.raises(ValueError, match="confidence"):
            l3.upsert("user", "likes", "Python", confidence=1.1)

    def test_invalid_confidence_below_zero_raises(self, l3):
        with pytest.raises(ValueError, match="confidence"):
            l3.upsert("user", "likes", "Python", confidence=-0.1)


# ---------------------------------------------------------------------------
# Persistence — vector index rebuild on simulated process restart
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_vector_index_rebuilt_from_sqlite(self, db):
        """After process restart (new L3 instance same DB), triples must be
        searchable without any re-insertion."""
        l3_first = L3SemanticMemory(db)
        l3_first.upsert("user", "likes", "Python")

        # Simulate restart: new L3 instance over the same DB.
        l3_second = L3SemanticMemory(db)
        results = l3_second.search("Python")
        assert len(results) >= 1
        assert results[0].value == "Python"

    def test_superseded_not_rebuilt_in_vector_index(self, db):
        """Superseded triples must not surface in search after rebuild."""
        l3_first = L3SemanticMemory(db)
        l3_first.upsert("user", "likes", "Python")
        l3_first.upsert("user", "likes", "Rust")

        l3_second = L3SemanticMemory(db)
        results = l3_second.search("user likes Python Rust")
        values = [r.value for r in results]
        assert "Rust" in values
        assert "Python" not in values

    def test_count_survives_restart(self, db):
        l3_first = L3SemanticMemory(db)
        l3_first.upsert("user", "likes", "Python")
        l3_first.upsert("user", "dislikes", "Java")

        l3_second = L3SemanticMemory(db)
        assert l3_second.count() == 2

    def test_get_survives_restart(self, db):
        l3_first = L3SemanticMemory(db)
        l3_first.upsert("user", "likes", "Python")

        l3_second = L3SemanticMemory(db)
        item = l3_second.get("user", "likes")
        assert item is not None
        assert item.value == "Python"
