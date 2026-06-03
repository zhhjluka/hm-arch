"""Tests for L3SemanticMemory.

Coverage
--------
Construction
* Construction with default LocalVectorStore.
* Construction with a supplied vector store.
* Layer index is 3.
* Invalid default_confidence raises ValueError.
* Invalid default_importance raises ValueError.

upsert() — return value
* Returns a non-empty string memory_id.
* Returns unique ids for different (entity, relation, value) triples.

upsert() — SQLite persistence (memory_index)
* Writes a row to memory_index with layer=3 and status='active'.
* Writes correct importance to memory_index.
* Writes correct timestamps to memory_index.

upsert() — SQLite persistence (semantics)
* Writes entity, relation, value to the semantics table.
* Writes confidence to the semantics table.
* Default version is 1 for a brand-new triple.

upsert() — idempotency
* Re-upserting the same (entity, relation, value) returns the same memory_id.
* Does not create a duplicate row in memory_index.
* Does not create a duplicate row in semantics.

upsert() — conflict / supersession
* Upserting a new value for the same (entity, relation) marks the old triple
  as 'superseded' in memory_index.
* The superseded row's superseded_by column points to the new memory_id.
* The new triple has version = old_version + 1.
* Only one active triple exists per (entity, relation) after conflict.
* count('active') stays at 1 after two conflicting upserts.
* count('superseded') increments with each conflict.
* Multiple consecutive value changes chain supersession correctly.

search() — basics
* Returns empty list when store is empty.
* Returns SemanticFact objects.
* Finds a triple that was upserted.
* Respects top_k.
* Superseded triples are NOT returned by search().

search() — ranking
* Latest active value ranks above superseded values (active is only one returned).
* Exact-match content ranks first.

search() — entity/relation filters
* entity filter prunes results to matching entity only.
* relation filter prunes results to matching relation only.

search() — CJK
* CJK entity/relation/value triples are searchable by CJK query tokens.

get_by_entity_relation()
* Returns the active fact for a known (entity, relation).
* Returns None when (entity, relation) does not exist.
* Returns the latest active value when there has been a conflict.

count()
* Zero for an empty layer.
* Increments for each new active triple.
* Superseded triples counted under 'superseded' status.

Persistence across restart (on-disk DB)
* Closing and reopening the DB preserves active triples.
* After restart, search() finds previously upserted triples.
* Supersession state is preserved across restarts.
* count() is consistent after restart.

Importability
* L3SemanticMemory importable from hm_arch.layers.
* SemanticFact importable from hm_arch.layers.

SemanticFact fields
* memory_id, entity, relation, value, confidence, version, status,
  created_at, relevance, source_episodes, metadata are all present.
* created_at is a timezone-aware UTC datetime.
* relevance > 0 for a matched search result.

source_episodes round-trip
* source_episodes list is stored and returned correctly.

Custom confidence round-trip
* Explicit confidence is stored and surfaced.

Custom metadata round-trip
* Explicit metadata is stored and returned.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hm_arch.layers import L3SemanticMemory, SemanticFact
from hm_arch.storage.sqlite import SQLiteStore
from hm_arch.storage.vector import LocalVectorStore


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_db(path: str = ":memory:") -> SQLiteStore:
    """Return a connected, schema-initialised SQLiteStore."""
    db = SQLiteStore(path)
    db.connect()
    db.initialize_schema()
    return db


@pytest.fixture()
def db() -> SQLiteStore:
    """In-memory SQLiteStore for fast isolated tests."""
    store = _make_db()
    yield store
    store.close()


@pytest.fixture()
def l3(db: SQLiteStore) -> L3SemanticMemory:
    """L3SemanticMemory backed by an in-memory DB."""
    return L3SemanticMemory(db)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_layer_index_is_three() -> None:
    assert L3SemanticMemory.LAYER_INDEX == 3


def test_construction_with_default_vector_store(db: SQLiteStore) -> None:
    l3 = L3SemanticMemory(db)
    assert l3 is not None


def test_construction_with_supplied_vector_store(db: SQLiteStore) -> None:
    vs = LocalVectorStore()
    l3 = L3SemanticMemory(db, vector_store=vs)
    assert l3 is not None


def test_invalid_default_confidence_raises(db: SQLiteStore) -> None:
    with pytest.raises(ValueError, match="default_confidence"):
        L3SemanticMemory(db, default_confidence=1.5)


def test_invalid_default_importance_raises(db: SQLiteStore) -> None:
    with pytest.raises(ValueError, match="default_importance"):
        L3SemanticMemory(db, default_importance=-0.1)


# ---------------------------------------------------------------------------
# Importability
# ---------------------------------------------------------------------------


def test_l3_importable_from_layers_package() -> None:
    from hm_arch.layers import L3SemanticMemory as L3  # noqa: F401

    assert L3 is not None


def test_semantic_fact_importable_from_layers_package() -> None:
    from hm_arch.layers import SemanticFact as SF  # noqa: F401

    assert SF is not None


# ---------------------------------------------------------------------------
# upsert() — return value
# ---------------------------------------------------------------------------


def test_upsert_returns_string(l3: L3SemanticMemory) -> None:
    mid = l3.upsert("user", "likes", "Python")
    assert isinstance(mid, str)
    assert len(mid) > 0


def test_upsert_returns_unique_ids_for_different_triples(l3: L3SemanticMemory) -> None:
    id1 = l3.upsert("user", "likes", "Python")
    id2 = l3.upsert("user", "uses", "vim")
    id3 = l3.upsert("agent", "prefers", "Rust")
    assert len({id1, id2, id3}) == 3


# ---------------------------------------------------------------------------
# upsert() — SQLite persistence (memory_index)
# ---------------------------------------------------------------------------


def test_upsert_persists_memory_index_row(db: SQLiteStore, l3: L3SemanticMemory) -> None:
    mid = l3.upsert("user", "likes", "Python")
    rows = db.query("SELECT * FROM memory_index WHERE id = ?", (mid,))
    assert len(rows) == 1


def test_upsert_memory_index_layer_is_three(db: SQLiteStore, l3: L3SemanticMemory) -> None:
    mid = l3.upsert("user", "likes", "Python")
    rows = db.query("SELECT layer FROM memory_index WHERE id = ?", (mid,))
    assert rows[0]["layer"] == 3


def test_upsert_memory_index_status_is_active(db: SQLiteStore, l3: L3SemanticMemory) -> None:
    mid = l3.upsert("user", "likes", "Python")
    rows = db.query("SELECT status FROM memory_index WHERE id = ?", (mid,))
    assert rows[0]["status"] == "active"


def test_upsert_memory_index_has_timestamps(db: SQLiteStore, l3: L3SemanticMemory) -> None:
    mid = l3.upsert("user", "likes", "Python")
    rows = db.query("SELECT created_at, updated_at FROM memory_index WHERE id = ?", (mid,))
    assert rows[0]["created_at"] is not None
    assert rows[0]["updated_at"] is not None


def test_upsert_default_importance_applied(db: SQLiteStore) -> None:
    l3 = L3SemanticMemory(db, default_importance=0.7)
    mid = l3.upsert("user", "likes", "Python")
    rows = db.query("SELECT importance FROM memory_index WHERE id = ?", (mid,))
    assert rows[0]["importance"] == pytest.approx(0.7)


def test_upsert_explicit_importance_overrides_default(db: SQLiteStore, l3: L3SemanticMemory) -> None:
    mid = l3.upsert("user", "likes", "Python", importance=0.3)
    rows = db.query("SELECT importance FROM memory_index WHERE id = ?", (mid,))
    assert rows[0]["importance"] == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# upsert() — SQLite persistence (semantics)
# ---------------------------------------------------------------------------


def test_upsert_persists_semantics_row(db: SQLiteStore, l3: L3SemanticMemory) -> None:
    mid = l3.upsert("user", "likes", "Python")
    rows = db.query("SELECT * FROM semantics WHERE memory_id = ?", (mid,))
    assert len(rows) == 1


def test_upsert_entity_stored(db: SQLiteStore, l3: L3SemanticMemory) -> None:
    mid = l3.upsert("user", "likes", "Python")
    rows = db.query("SELECT entity FROM semantics WHERE memory_id = ?", (mid,))
    assert rows[0]["entity"] == "user"


def test_upsert_relation_stored(db: SQLiteStore, l3: L3SemanticMemory) -> None:
    mid = l3.upsert("user", "likes", "Python")
    rows = db.query("SELECT relation FROM semantics WHERE memory_id = ?", (mid,))
    assert rows[0]["relation"] == "likes"


def test_upsert_value_stored(db: SQLiteStore, l3: L3SemanticMemory) -> None:
    mid = l3.upsert("user", "likes", "Python")
    rows = db.query("SELECT value FROM semantics WHERE memory_id = ?", (mid,))
    assert rows[0]["value"] == "Python"


def test_upsert_confidence_stored(db: SQLiteStore, l3: L3SemanticMemory) -> None:
    mid = l3.upsert("user", "likes", "Python", confidence=0.9)
    rows = db.query("SELECT confidence FROM semantics WHERE memory_id = ?", (mid,))
    assert rows[0]["confidence"] == pytest.approx(0.9)


def test_upsert_default_version_is_one(db: SQLiteStore, l3: L3SemanticMemory) -> None:
    mid = l3.upsert("user", "likes", "Python")
    rows = db.query("SELECT version FROM semantics WHERE memory_id = ?", (mid,))
    assert rows[0]["version"] == 1


def test_upsert_source_episodes_stored(db: SQLiteStore, l3: L3SemanticMemory) -> None:
    import json

    mid = l3.upsert("user", "likes", "Python", source_episodes=["ep1", "ep2"])
    rows = db.query("SELECT source_episodes FROM semantics WHERE memory_id = ?", (mid,))
    assert json.loads(rows[0]["source_episodes"]) == ["ep1", "ep2"]


def test_upsert_custom_metadata_stored(db: SQLiteStore, l3: L3SemanticMemory) -> None:
    import json

    mid = l3.upsert("user", "likes", "Python", metadata={"source": "test"})
    rows = db.query("SELECT metadata FROM memory_index WHERE id = ?", (mid,))
    meta = json.loads(rows[0]["metadata"])
    assert meta["source"] == "test"
    assert "hm_arch_strength" in meta


# ---------------------------------------------------------------------------
# upsert() — validation
# ---------------------------------------------------------------------------


def test_upsert_invalid_confidence_raises(l3: L3SemanticMemory) -> None:
    with pytest.raises(ValueError, match="confidence"):
        l3.upsert("user", "likes", "Python", confidence=1.5)


def test_upsert_invalid_importance_raises(l3: L3SemanticMemory) -> None:
    with pytest.raises(ValueError, match="importance"):
        l3.upsert("user", "likes", "Python", importance=-0.1)


# ---------------------------------------------------------------------------
# upsert() — idempotency
# ---------------------------------------------------------------------------


def test_upsert_same_triple_returns_same_id(l3: L3SemanticMemory) -> None:
    id1 = l3.upsert("user", "likes", "Python")
    id2 = l3.upsert("user", "likes", "Python")
    assert id1 == id2


def test_upsert_same_triple_no_duplicate_memory_index(
    db: SQLiteStore, l3: L3SemanticMemory
) -> None:
    l3.upsert("user", "likes", "Python")
    l3.upsert("user", "likes", "Python")
    rows = db.query(
        "SELECT COUNT(*) FROM memory_index WHERE layer = 3 AND status = 'active'"
    )
    assert rows[0][0] == 1


def test_upsert_same_triple_no_duplicate_semantics(
    db: SQLiteStore, l3: L3SemanticMemory
) -> None:
    mid = l3.upsert("user", "likes", "Python")
    l3.upsert("user", "likes", "Python")
    rows = db.query("SELECT COUNT(*) FROM semantics WHERE memory_id = ?", (mid,))
    assert rows[0][0] == 1


# ---------------------------------------------------------------------------
# upsert() — conflict / supersession (core acceptance criteria)
# ---------------------------------------------------------------------------


def test_conflict_marks_old_triple_as_superseded(
    db: SQLiteStore, l3: L3SemanticMemory
) -> None:
    old_id = l3.upsert("user", "likes", "Python")
    l3.upsert("user", "likes", "Rust")
    rows = db.query("SELECT status FROM memory_index WHERE id = ?", (old_id,))
    assert rows[0]["status"] == "superseded"


def test_conflict_superseded_by_points_to_new_id(
    db: SQLiteStore, l3: L3SemanticMemory
) -> None:
    old_id = l3.upsert("user", "likes", "Python")
    new_id = l3.upsert("user", "likes", "Rust")
    rows = db.query("SELECT superseded_by FROM memory_index WHERE id = ?", (old_id,))
    assert rows[0]["superseded_by"] == new_id


def test_conflict_new_triple_is_active(
    db: SQLiteStore, l3: L3SemanticMemory
) -> None:
    l3.upsert("user", "likes", "Python")
    new_id = l3.upsert("user", "likes", "Rust")
    rows = db.query("SELECT status FROM memory_index WHERE id = ?", (new_id,))
    assert rows[0]["status"] == "active"


def test_conflict_new_version_increments(
    db: SQLiteStore, l3: L3SemanticMemory
) -> None:
    l3.upsert("user", "likes", "Python")
    new_id = l3.upsert("user", "likes", "Rust")
    rows = db.query("SELECT version FROM semantics WHERE memory_id = ?", (new_id,))
    assert rows[0]["version"] == 2


def test_conflict_only_one_active_triple_per_entity_relation(
    db: SQLiteStore, l3: L3SemanticMemory
) -> None:
    l3.upsert("user", "likes", "Python")
    l3.upsert("user", "likes", "Rust")
    rows = db.query(
        """
        SELECT COUNT(*)
        FROM   memory_index mi
        JOIN   semantics s ON s.memory_id = mi.id
        WHERE  s.entity   = 'user'
          AND  s.relation = 'likes'
          AND  mi.layer   = 3
          AND  mi.status  = 'active'
        """
    )
    assert rows[0][0] == 1


def test_conflict_count_active_stays_at_one(l3: L3SemanticMemory) -> None:
    l3.upsert("user", "likes", "Python")
    l3.upsert("user", "likes", "Rust")
    assert l3.count("active") == 1


def test_conflict_count_superseded_increments(l3: L3SemanticMemory) -> None:
    l3.upsert("user", "likes", "Python")
    l3.upsert("user", "likes", "Rust")
    assert l3.count("superseded") == 1


def test_conflict_chain_three_values(
    db: SQLiteStore, l3: L3SemanticMemory
) -> None:
    """Python → Rust → Go: two superseded, one active."""
    id1 = l3.upsert("user", "likes", "Python")
    id2 = l3.upsert("user", "likes", "Rust")
    id3 = l3.upsert("user", "likes", "Go")

    # id1 and id2 should both be superseded.
    rows1 = db.query("SELECT status FROM memory_index WHERE id = ?", (id1,))
    rows2 = db.query("SELECT status FROM memory_index WHERE id = ?", (id2,))
    rows3 = db.query("SELECT status FROM memory_index WHERE id = ?", (id3,))
    assert rows1[0]["status"] == "superseded"
    assert rows2[0]["status"] == "superseded"
    assert rows3[0]["status"] == "active"

    # Version should be 3 for the latest.
    rows_v = db.query("SELECT version FROM semantics WHERE memory_id = ?", (id3,))
    assert rows_v[0]["version"] == 3

    assert l3.count("active") == 1
    assert l3.count("superseded") == 2


def test_different_relations_are_independent(l3: L3SemanticMemory) -> None:
    """Changing 'likes' does not supersede 'uses'."""
    id_likes = l3.upsert("user", "likes", "Python")
    id_uses = l3.upsert("user", "uses", "vim")
    l3.upsert("user", "likes", "Rust")

    # 'uses vim' should still be active.
    assert l3.count("active") == 2
    fact = l3.get_by_entity_relation("user", "uses")
    assert fact is not None
    assert fact.value == "vim"
    assert fact.memory_id == id_uses


# ---------------------------------------------------------------------------
# search() — basics
# ---------------------------------------------------------------------------


def test_search_empty_store_returns_empty(l3: L3SemanticMemory) -> None:
    results = l3.search("Python")
    assert results == []


def test_search_returns_semantic_facts(l3: L3SemanticMemory) -> None:
    l3.upsert("user", "likes", "Python")
    results = l3.search("Python")
    assert all(isinstance(r, SemanticFact) for r in results)


def test_search_finds_upserted_triple(l3: L3SemanticMemory) -> None:
    mid = l3.upsert("user", "likes", "Python")
    results = l3.search("Python")
    ids = [r.memory_id for r in results]
    assert mid in ids


def test_search_respects_top_k(l3: L3SemanticMemory) -> None:
    for i in range(10):
        l3.upsert(f"entity{i}", "has", f"value{i}")
    results = l3.search("entity has value", top_k=3)
    assert len(results) <= 3


def test_search_does_not_return_superseded(l3: L3SemanticMemory) -> None:
    old_id = l3.upsert("user", "likes", "Python")
    l3.upsert("user", "likes", "Rust")
    results = l3.search("Python likes user")
    ids = [r.memory_id for r in results]
    assert old_id not in ids


def test_search_returns_active_triple_after_conflict(l3: L3SemanticMemory) -> None:
    l3.upsert("user", "likes", "Python")
    new_id = l3.upsert("user", "likes", "Rust")
    results = l3.search("user likes Rust")
    assert results[0].memory_id == new_id
    assert results[0].value == "Rust"


# ---------------------------------------------------------------------------
# search() — ranking
# ---------------------------------------------------------------------------


def test_search_highest_relevance_first(l3: L3SemanticMemory) -> None:
    l3.upsert("user", "likes", "Python")
    l3.upsert("agent", "prefers", "Java")
    l3.upsert("user", "uses", "Python scripting")
    results = l3.search("user likes Python", top_k=5)
    assert len(results) > 0
    # All scores should be descending.
    scores = [r.relevance for r in results]
    assert scores == sorted(scores, reverse=True)


def test_search_exact_content_ranks_first(l3: L3SemanticMemory) -> None:
    l3.upsert("user", "likes", "Python")
    l3.upsert("user", "dislikes", "Java")
    l3.upsert("agent", "prefers", "C++")
    results = l3.search("user likes Python", top_k=5)
    assert results[0].entity == "user"
    assert results[0].relation == "likes"
    assert results[0].value == "Python"


# ---------------------------------------------------------------------------
# search() — entity / relation filters
# ---------------------------------------------------------------------------


def test_search_entity_filter(l3: L3SemanticMemory) -> None:
    l3.upsert("user", "likes", "Python")
    l3.upsert("agent", "likes", "Python")
    results = l3.search("likes Python", entity="user")
    assert all(r.entity == "user" for r in results)


def test_search_relation_filter(l3: L3SemanticMemory) -> None:
    l3.upsert("user", "likes", "Python")
    l3.upsert("user", "uses", "Python")
    results = l3.search("user Python", relation="likes")
    assert all(r.relation == "likes" for r in results)


# ---------------------------------------------------------------------------
# search() — filter pushdown regression tests
# (>20 unrelated triples that score higher must not hide the filtered match)
# ---------------------------------------------------------------------------


def test_search_entity_filter_not_lost_among_many_unrelated(
    l3: L3SemanticMemory,
) -> None:
    """Entity filter pushdown: target is found even when 25 unrelated triples
    all score higher on the query string.

    The needle triple has low token-overlap with the query ("common term
    value"), while every bulk triple has high overlap (entity and value contain
    all three query tokens).  Without filter pushdown the old code's 20-item
    window would fill entirely with bulk triples, silently dropping the needle.
    With filter pushdown the vector store only considers needle_entity triples,
    so top_k=1 is sufficient.
    """
    # 25 bulk triples — each contains all three query tokens in its text
    # ("bulk{i} common term value"), giving a high overlap score.
    for i in range(25):
        l3.upsert(f"bulk{i}", "common", "term value")

    # Needle triple — entity differs; its text ("needle_entity likes
    # needle_value") shares only "value" with the query, ranking far below
    # the 25 bulk triples without a filter.
    needle_id = l3.upsert("needle_entity", "likes", "needle_value")

    results = l3.search("common term value", top_k=1, entity="needle_entity")
    ids = [r.memory_id for r in results]
    assert needle_id in ids, (
        "entity filter pushdown must surface needle_entity triple even when "
        "25 higher-scoring unrelated triples exist"
    )
    assert all(r.entity == "needle_entity" for r in results)


def test_search_relation_filter_not_lost_among_many_unrelated(
    l3: L3SemanticMemory,
) -> None:
    """Relation filter pushdown: target is found even when 25 unrelated triples
    all score higher on the query string.

    Mirrors the entity-filter regression test but filters on relation instead.
    """
    for i in range(25):
        l3.upsert(f"bulk{i}", "common", "term value")

    needle_id = l3.upsert("user", "needle_relation", "needle_value")

    results = l3.search("common term value", top_k=1, relation="needle_relation")
    ids = [r.memory_id for r in results]
    assert needle_id in ids, (
        "relation filter pushdown must surface needle_relation triple even when "
        "25 higher-scoring unrelated triples exist"
    )
    assert all(r.relation == "needle_relation" for r in results)


def test_search_combined_entity_relation_filter_pushdown(
    l3: L3SemanticMemory,
) -> None:
    """Both entity and relation filters are pushed down simultaneously."""
    for i in range(25):
        l3.upsert(f"bulk{i}", "common", "term value")

    needle_id = l3.upsert("needle_entity", "needle_relation", "needle_value")

    results = l3.search(
        "common term value",
        top_k=1,
        entity="needle_entity",
        relation="needle_relation",
    )
    ids = [r.memory_id for r in results]
    assert needle_id in ids, (
        "combined entity+relation filter pushdown must surface the needle triple"
    )


def test_search_top_k_zero_returns_empty(l3: L3SemanticMemory) -> None:
    """top_k=0 returns an empty list immediately."""
    l3.upsert("user", "likes", "Python")
    results = l3.search("Python", top_k=0)
    assert results == []


def test_search_top_k_negative_returns_empty(l3: L3SemanticMemory) -> None:
    """Negative top_k returns an empty list immediately."""
    l3.upsert("user", "likes", "Python")
    results = l3.search("Python", top_k=-5)
    assert results == []


# ---------------------------------------------------------------------------
# search() — CJK (Chinese/Japanese/Korean) support
# ---------------------------------------------------------------------------


def test_search_cjk_triple_is_searchable(l3: L3SemanticMemory) -> None:
    """CJK entity/relation/value triples are found by CJK query tokens."""
    mid = l3.upsert("用户", "喜欢", "Python")
    results = l3.search("用户 喜欢", top_k=5)
    ids = [r.memory_id for r in results]
    assert mid in ids


def test_search_cjk_value_query(l3: L3SemanticMemory) -> None:
    mid = l3.upsert("用户", "偏好语言", "Python")
    results = l3.search("偏好语言 Python", top_k=5)
    ids = [r.memory_id for r in results]
    assert mid in ids


def test_search_mixed_cjk_ascii_triple(l3: L3SemanticMemory) -> None:
    mid = l3.upsert("user", "偏好", "Python")
    results = l3.search("user 偏好 Python", top_k=5)
    ids = [r.memory_id for r in results]
    assert mid in ids


# ---------------------------------------------------------------------------
# get_by_entity_relation()
# ---------------------------------------------------------------------------


def test_get_by_entity_relation_returns_fact(l3: L3SemanticMemory) -> None:
    mid = l3.upsert("user", "likes", "Python")
    fact = l3.get_by_entity_relation("user", "likes")
    assert fact is not None
    assert fact.memory_id == mid
    assert fact.entity == "user"
    assert fact.relation == "likes"
    assert fact.value == "Python"


def test_get_by_entity_relation_returns_none_when_missing(l3: L3SemanticMemory) -> None:
    fact = l3.get_by_entity_relation("nobody", "knows")
    assert fact is None


def test_get_by_entity_relation_returns_latest_after_conflict(l3: L3SemanticMemory) -> None:
    l3.upsert("user", "likes", "Python")
    new_id = l3.upsert("user", "likes", "Rust")
    fact = l3.get_by_entity_relation("user", "likes")
    assert fact is not None
    assert fact.memory_id == new_id
    assert fact.value == "Rust"


# ---------------------------------------------------------------------------
# count()
# ---------------------------------------------------------------------------


def test_count_zero_on_empty(l3: L3SemanticMemory) -> None:
    assert l3.count() == 0


def test_count_increments_per_upsert(l3: L3SemanticMemory) -> None:
    l3.upsert("user", "likes", "Python")
    assert l3.count() == 1
    l3.upsert("user", "uses", "vim")
    assert l3.count() == 2


def test_count_idempotent_upsert_does_not_increment(l3: L3SemanticMemory) -> None:
    l3.upsert("user", "likes", "Python")
    l3.upsert("user", "likes", "Python")
    assert l3.count() == 1


def test_count_superseded_zero_initially(l3: L3SemanticMemory) -> None:
    l3.upsert("user", "likes", "Python")
    assert l3.count("superseded") == 0


def test_count_superseded_after_conflict(l3: L3SemanticMemory) -> None:
    l3.upsert("user", "likes", "Python")
    l3.upsert("user", "likes", "Rust")
    assert l3.count("superseded") == 1


# ---------------------------------------------------------------------------
# SemanticFact field correctness
# ---------------------------------------------------------------------------


def test_semantic_fact_fields_present(l3: L3SemanticMemory) -> None:
    mid = l3.upsert("user", "likes", "Python")
    results = l3.search("user likes Python")
    assert len(results) >= 1
    fact = results[0]
    assert fact.memory_id == mid
    assert fact.entity == "user"
    assert fact.relation == "likes"
    assert fact.value == "Python"
    assert isinstance(fact.confidence, float)
    assert isinstance(fact.version, int)
    assert fact.status == "active"
    assert isinstance(fact.created_at, datetime)
    assert isinstance(fact.relevance, float)
    assert isinstance(fact.source_episodes, list)
    assert isinstance(fact.metadata, dict)


def test_semantic_fact_created_at_is_utc(l3: L3SemanticMemory) -> None:
    l3.upsert("user", "likes", "Python")
    results = l3.search("user likes Python")
    assert results[0].created_at.tzinfo == timezone.utc


def test_semantic_fact_relevance_positive_for_match(l3: L3SemanticMemory) -> None:
    l3.upsert("user", "likes", "Python")
    results = l3.search("user likes Python")
    assert results[0].relevance > 0.0


def test_semantic_fact_relevance_in_unit_interval(l3: L3SemanticMemory) -> None:
    l3.upsert("user", "likes", "Python")
    results = l3.search("user likes Python")
    assert 0.0 <= results[0].relevance <= 1.0


def test_semantic_fact_source_episodes_roundtrip(
    db: SQLiteStore, l3: L3SemanticMemory
) -> None:
    mid = l3.upsert("user", "likes", "Python", source_episodes=["ep_abc", "ep_def"])
    results = l3.search("user likes Python")
    assert results[0].source_episodes == ["ep_abc", "ep_def"]


def test_semantic_fact_confidence_roundtrip(l3: L3SemanticMemory) -> None:
    mid = l3.upsert("user", "likes", "Python", confidence=0.75)
    results = l3.search("user likes Python")
    assert results[0].confidence == pytest.approx(0.75)


def test_semantic_fact_metadata_roundtrip(l3: L3SemanticMemory) -> None:
    mid = l3.upsert("user", "likes", "Python", metadata={"key": "val"})
    results = l3.search("user likes Python")
    assert results[0].metadata["key"] == "val"
    assert "hm_arch_strength" in results[0].metadata


# ---------------------------------------------------------------------------
# Persistence across restart (on-disk DB)
# ---------------------------------------------------------------------------


def test_restart_preserves_semantic_in_sqlite() -> None:
    """Semantic triples survive closing and reopening the SQLiteStore."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test_l3.db")

        db1 = _make_db(db_path)
        l3_a = L3SemanticMemory(db1)
        mid = l3_a.upsert("user", "likes", "Python")
        db1.close()

        db2 = _make_db(db_path)
        rows = db2.query(
            "SELECT * FROM semantics WHERE memory_id = ?", (mid,)
        )
        assert len(rows) == 1
        assert rows[0]["value"] == "Python"
        db2.close()


def test_restart_search_finds_persisted_triple() -> None:
    """After restart, search() finds content from before the restart."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test_l3.db")

        db1 = _make_db(db_path)
        l3_a = L3SemanticMemory(db1)
        mid = l3_a.upsert("user", "likes", "Python")
        db1.close()

        db2 = _make_db(db_path)
        l3_b = L3SemanticMemory(db2)
        results = l3_b.search("user likes Python", top_k=5)
        db2.close()

        ids = [r.memory_id for r in results]
        assert mid in ids


def test_restart_supersession_preserved() -> None:
    """Supersession state is preserved after restart."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test_l3.db")

        db1 = _make_db(db_path)
        l3_a = L3SemanticMemory(db1)
        old_id = l3_a.upsert("user", "likes", "Python")
        new_id = l3_a.upsert("user", "likes", "Rust")
        db1.close()

        db2 = _make_db(db_path)
        rows_old = db2.query(
            "SELECT status, superseded_by FROM memory_index WHERE id = ?", (old_id,)
        )
        rows_new = db2.query(
            "SELECT status FROM memory_index WHERE id = ?", (new_id,)
        )
        db2.close()

        assert rows_old[0]["status"] == "superseded"
        assert rows_old[0]["superseded_by"] == new_id
        assert rows_new[0]["status"] == "active"


def test_restart_count_preserved() -> None:
    """count() is consistent after reopening the DB."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test_l3.db")

        db1 = _make_db(db_path)
        l3_a = L3SemanticMemory(db1)
        l3_a.upsert("user", "likes", "Python")
        l3_a.upsert("user", "uses", "vim")
        l3_a.upsert("user", "likes", "Rust")  # supersedes Python
        db1.close()

        db2 = _make_db(db_path)
        l3_b = L3SemanticMemory(db2)
        assert l3_b.count("active") == 2       # likes→Rust, uses→vim
        assert l3_b.count("superseded") == 1   # likes→Python
        db2.close()


def test_restart_search_excludes_superseded_after_restart() -> None:
    """After restart, superseded triples are not returned by search()."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test_l3.db")

        db1 = _make_db(db_path)
        l3_a = L3SemanticMemory(db1)
        old_id = l3_a.upsert("user", "likes", "Python")
        new_id = l3_a.upsert("user", "likes", "Rust")
        db1.close()

        db2 = _make_db(db_path)
        l3_b = L3SemanticMemory(db2)
        # Search for the old value — should NOT surface the superseded triple.
        results = l3_b.search("user likes Python Rust", top_k=5)
        db2.close()

        ids = [r.memory_id for r in results]
        assert old_id not in ids
        assert new_id in ids


# ---------------------------------------------------------------------------
# max_memories capacity
# ---------------------------------------------------------------------------


def test_max_memories_rejects_net_new_fact_at_capacity(db) -> None:
    l3 = L3SemanticMemory(db, max_memories=1)
    l3.upsert("user", "likes", "Python")
    with pytest.raises(ValueError, match="max_memories"):
        l3.upsert("team", "likes", "Java")


def test_max_memories_allows_superseding_replacement_at_capacity(db) -> None:
    l3 = L3SemanticMemory(db, max_memories=1)
    l3.upsert("user", "likes", "Python")
    rust_id = l3.upsert("user", "likes", "Rust")
    fact = l3.get_by_entity_relation("user", "likes")
    assert fact is not None
    assert fact.memory_id == rust_id
    assert fact.value == "Rust"
    assert l3.count(status="active") == 1


# ---------------------------------------------------------------------------
# merge_redundant_active_pairs — cross-key safety
# ---------------------------------------------------------------------------


class TestMergeRedundantActivePairs:
    """Regression tests for safe redundant-fact merging."""

    def test_same_value_different_entity_not_merged(self, db):
        l3 = L3SemanticMemory(db)
        l3.upsert("user", "prefers", "Python")
        l3.upsert("assistant", "prefers", "Python")

        merged = l3.merge_redundant_active_pairs(0.5)

        assert merged == 0
        assert l3.count(status="active") == 2

    def test_same_entity_different_relation_not_merged(self, db):
        l3 = L3SemanticMemory(db)
        l3.upsert("user", "prefers", "Python")
        l3.upsert("user", "uses", "Python")

        merged = l3.merge_redundant_active_pairs(0.5)

        assert merged == 0
        assert l3.count(status="active") == 2


# ---------------------------------------------------------------------------
# Isolation — two independent L3 instances on separate DBs
# ---------------------------------------------------------------------------


def test_two_l3_instances_are_independent() -> None:
    db_a = _make_db()
    db_b = _make_db()
    l3_a = L3SemanticMemory(db_a)
    l3_b = L3SemanticMemory(db_b)

    l3_a.upsert("user", "likes", "Python")
    assert l3_a.count() == 1
    assert l3_b.count() == 0

    results_b = l3_b.search("Python")
    assert results_b == []

    db_a.close()
    db_b.close()
