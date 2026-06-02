"""Tests for L2EpisodicBuffer.

Coverage
--------
* Construction with default LocalVectorStore and with a supplied store.
* encode() persists a row in memory_index (correct layer, status, importance).
* encode() persists a row in episodes (content, event_type, emotion_score).
* encode() upserts the content into the vector store.
* encode() returns a unique string memory_id.
* retrieve() returns EpisodicItem objects ranked by relevance.
* retrieve() respects top_k.
* retrieve() returns empty list when store is empty.
* retrieve() carries correct retention metadata from memory_index.
* Persistence: reopening the same on-disk SQLite file preserves episodes
  and they are found by retrieve().
* Vector index is rebuilt correctly after restart (SQLite as source of truth).
* Layer index is 2.
* count() returns correct number of active episodes.
* EpisodicItem fields: memory_id, layer, content, event_type, importance,
  retention, relevance, created_at, metadata.
* Custom importance override is stored and returned.
* Custom metadata is stored and returned.
* Different EventType values are accepted.
* emotion_score and context_window are stored (round-trip via DB).
* Importable from hm_arch.layers package.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hm_arch.layers import EpisodicItem, L2EpisodicBuffer
from hm_arch.storage.sqlite import SQLiteStore
from hm_arch.storage.vector import LocalVectorStore
from hm_arch.types import EventType


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
def l2(db: SQLiteStore) -> L2EpisodicBuffer:
    """L2EpisodicBuffer backed by an in-memory DB."""
    return L2EpisodicBuffer(db)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_layer_index_is_two() -> None:
    assert L2EpisodicBuffer.LAYER_INDEX == 2


def test_construction_with_default_vector_store(db: SQLiteStore) -> None:
    l2 = L2EpisodicBuffer(db)
    assert l2 is not None


def test_construction_with_supplied_vector_store(db: SQLiteStore) -> None:
    vs = LocalVectorStore()
    l2 = L2EpisodicBuffer(db, vector_store=vs)
    assert l2 is not None


def test_importable_from_layers_package() -> None:
    from hm_arch.layers import L2EpisodicBuffer as L2  # noqa: F401

    assert L2 is not None


def test_episodic_item_importable_from_layers_package() -> None:
    from hm_arch.layers import EpisodicItem as EI  # noqa: F401

    assert EI is not None


# ---------------------------------------------------------------------------
# encode() — return value
# ---------------------------------------------------------------------------


def test_encode_returns_string(l2: L2EpisodicBuffer) -> None:
    mid = l2.encode("hello world")
    assert isinstance(mid, str)
    assert len(mid) > 0


def test_encode_returns_unique_ids(l2: L2EpisodicBuffer) -> None:
    ids = {l2.encode(f"event {i}") for i in range(10)}
    assert len(ids) == 10


# ---------------------------------------------------------------------------
# encode() — SQLite persistence (memory_index)
# ---------------------------------------------------------------------------


def test_encode_persists_memory_index_row(db: SQLiteStore, l2: L2EpisodicBuffer) -> None:
    mid = l2.encode("test content")
    rows = db.query("SELECT * FROM memory_index WHERE id = ?", (mid,))
    assert len(rows) == 1


def test_encode_memory_index_layer_is_two(db: SQLiteStore, l2: L2EpisodicBuffer) -> None:
    mid = l2.encode("layer check")
    rows = db.query("SELECT layer FROM memory_index WHERE id = ?", (mid,))
    assert rows[0]["layer"] == 2


def test_encode_memory_index_status_is_active(db: SQLiteStore, l2: L2EpisodicBuffer) -> None:
    mid = l2.encode("status check")
    rows = db.query("SELECT status FROM memory_index WHERE id = ?", (mid,))
    assert rows[0]["status"] == "active"


def test_encode_memory_index_default_importance(db: SQLiteStore, l2: L2EpisodicBuffer) -> None:
    mid = l2.encode("importance check")
    rows = db.query("SELECT importance FROM memory_index WHERE id = ?", (mid,))
    assert rows[0]["importance"] == pytest.approx(0.5)


def test_encode_custom_importance(db: SQLiteStore, l2: L2EpisodicBuffer) -> None:
    mid = l2.encode("important event", importance=0.9)
    rows = db.query("SELECT importance FROM memory_index WHERE id = ?", (mid,))
    assert rows[0]["importance"] == pytest.approx(0.9)


def test_encode_initial_strength_and_retention(db: SQLiteStore, l2: L2EpisodicBuffer) -> None:
    mid = l2.encode("retention check")
    rows = db.query(
        "SELECT initial_strength, current_retention FROM memory_index WHERE id = ?",
        (mid,),
    )
    assert rows[0]["initial_strength"] == pytest.approx(1.0)
    assert rows[0]["current_retention"] == pytest.approx(1.0)


def test_encode_memory_index_has_timestamps(db: SQLiteStore, l2: L2EpisodicBuffer) -> None:
    mid = l2.encode("ts check")
    rows = db.query("SELECT created_at, updated_at FROM memory_index WHERE id = ?", (mid,))
    assert rows[0]["created_at"] is not None
    assert rows[0]["updated_at"] is not None


def test_encode_custom_metadata_stored(db: SQLiteStore, l2: L2EpisodicBuffer) -> None:
    import json

    mid = l2.encode("meta check", metadata={"source": "unit_test", "priority": 3})
    rows = db.query("SELECT metadata FROM memory_index WHERE id = ?", (mid,))
    stored = json.loads(rows[0]["metadata"])
    assert stored == {"source": "unit_test", "priority": 3}


# ---------------------------------------------------------------------------
# encode() — SQLite persistence (episodes)
# ---------------------------------------------------------------------------


def test_encode_persists_episode_row(db: SQLiteStore, l2: L2EpisodicBuffer) -> None:
    mid = l2.encode("episode content")
    rows = db.query("SELECT * FROM episodes WHERE memory_id = ?", (mid,))
    assert len(rows) == 1


def test_encode_episode_content_stored(db: SQLiteStore, l2: L2EpisodicBuffer) -> None:
    mid = l2.encode("episode text content")
    rows = db.query("SELECT content FROM episodes WHERE memory_id = ?", (mid,))
    assert rows[0]["content"] == "episode text content"


def test_encode_episode_event_type_stored(db: SQLiteStore, l2: L2EpisodicBuffer) -> None:
    mid = l2.encode("decision made", event_type=EventType.DECISION)
    rows = db.query("SELECT event_type FROM episodes WHERE memory_id = ?", (mid,))
    assert rows[0]["event_type"] == "decision"


def test_encode_episode_default_event_type(db: SQLiteStore, l2: L2EpisodicBuffer) -> None:
    mid = l2.encode("default event type")
    rows = db.query("SELECT event_type FROM episodes WHERE memory_id = ?", (mid,))
    assert rows[0]["event_type"] == "observation"


def test_encode_episode_emotion_score_stored(db: SQLiteStore, l2: L2EpisodicBuffer) -> None:
    mid = l2.encode("emotional event", emotion_score=0.8)
    rows = db.query("SELECT emotion_score FROM episodes WHERE memory_id = ?", (mid,))
    assert rows[0]["emotion_score"] == pytest.approx(0.8)


def test_encode_episode_context_window_stored(db: SQLiteStore, l2: L2EpisodicBuffer) -> None:
    mid = l2.encode("event with context", context_window="surrounding context here")
    rows = db.query("SELECT context_window FROM episodes WHERE memory_id = ?", (mid,))
    assert rows[0]["context_window"] == "surrounding context here"


def test_encode_episode_no_emotion_score_is_null(db: SQLiteStore, l2: L2EpisodicBuffer) -> None:
    mid = l2.encode("no emotion")
    rows = db.query("SELECT emotion_score FROM episodes WHERE memory_id = ?", (mid,))
    assert rows[0]["emotion_score"] is None


# ---------------------------------------------------------------------------
# encode() — various EventType values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "event_type,expected_str",
    [
        (EventType.CONVERSATION, "conversation"),
        (EventType.OBSERVATION, "observation"),
        (EventType.DECISION, "decision"),
        (EventType.ERROR, "error"),
        (EventType.CODE, "code"),
        (EventType.TASK, "task"),
        (EventType.SYSTEM, "system"),
    ],
)
def test_encode_all_event_types(
    db: SQLiteStore, l2: L2EpisodicBuffer, event_type: EventType, expected_str: str
) -> None:
    mid = l2.encode("typed event", event_type=event_type)
    rows = db.query("SELECT event_type FROM episodes WHERE memory_id = ?", (mid,))
    assert rows[0]["event_type"] == expected_str


# ---------------------------------------------------------------------------
# retrieve() — basics
# ---------------------------------------------------------------------------


def test_retrieve_empty_store_returns_empty(l2: L2EpisodicBuffer) -> None:
    results = l2.retrieve("any query")
    assert results == []


def test_retrieve_returns_episodic_items(l2: L2EpisodicBuffer) -> None:
    l2.encode("Python is a great language")
    results = l2.retrieve("Python")
    assert all(isinstance(r, EpisodicItem) for r in results)


def test_retrieve_finds_encoded_content(l2: L2EpisodicBuffer) -> None:
    mid = l2.encode("User prefers Python over Java")
    results = l2.retrieve("Python preference", top_k=5)
    ids = [r.memory_id for r in results]
    assert mid in ids


def test_retrieve_respects_top_k(l2: L2EpisodicBuffer) -> None:
    for i in range(10):
        l2.encode(f"Python event item {i}")
    results = l2.retrieve("Python event", top_k=3)
    assert len(results) <= 3


def test_retrieve_top_k_larger_than_store(l2: L2EpisodicBuffer) -> None:
    l2.encode("only one item")
    results = l2.retrieve("only one", top_k=100)
    assert len(results) == 1


def test_retrieve_ranked_by_relevance(l2: L2EpisodicBuffer) -> None:
    l2.encode("Java enterprise backend development")
    l2.encode("Python scripting language")
    l2.encode("Python machine learning deep learning")
    results = l2.retrieve("Python machine learning", top_k=3)
    assert results[0].content == "Python machine learning deep learning"


# ---------------------------------------------------------------------------
# retrieve() — EpisodicItem field correctness
# ---------------------------------------------------------------------------


def test_retrieve_item_layer_is_two(l2: L2EpisodicBuffer) -> None:
    l2.encode("layer test")
    results = l2.retrieve("layer test")
    assert results[0].layer == 2


def test_retrieve_item_content_matches(l2: L2EpisodicBuffer) -> None:
    l2.encode("exact content string")
    results = l2.retrieve("exact content string")
    assert results[0].content == "exact content string"


def test_retrieve_item_event_type_matches(l2: L2EpisodicBuffer) -> None:
    l2.encode("code event", event_type=EventType.CODE)
    results = l2.retrieve("code event")
    assert results[0].event_type == "code"


def test_retrieve_item_importance_matches_custom(l2: L2EpisodicBuffer) -> None:
    l2.encode("hi priority", importance=0.95)
    results = l2.retrieve("hi priority")
    assert results[0].importance == pytest.approx(0.95)


def test_retrieve_item_retention_is_one_for_new(l2: L2EpisodicBuffer) -> None:
    l2.encode("fresh episode")
    results = l2.retrieve("fresh episode")
    assert results[0].retention == pytest.approx(1.0)


def test_retrieve_item_relevance_is_positive(l2: L2EpisodicBuffer) -> None:
    l2.encode("Python relevance test")
    results = l2.retrieve("Python relevance")
    assert results[0].relevance > 0.0


def test_retrieve_item_relevance_in_unit_interval(l2: L2EpisodicBuffer) -> None:
    l2.encode("relevance bounds check")
    results = l2.retrieve("relevance bounds")
    assert 0.0 <= results[0].relevance <= 1.0


def test_retrieve_item_created_at_is_datetime(l2: L2EpisodicBuffer) -> None:
    l2.encode("timestamp test")
    results = l2.retrieve("timestamp test")
    assert isinstance(results[0].created_at, datetime)


def test_retrieve_item_created_at_is_utc(l2: L2EpisodicBuffer) -> None:
    l2.encode("utc check")
    results = l2.retrieve("utc check")
    assert results[0].created_at.tzinfo == timezone.utc


def test_retrieve_item_metadata_matches(l2: L2EpisodicBuffer) -> None:
    l2.encode("meta test", metadata={"key": "value", "n": 42})
    results = l2.retrieve("meta test")
    assert results[0].metadata == {"key": "value", "n": 42}


def test_retrieve_item_memory_id_matches_encode(l2: L2EpisodicBuffer) -> None:
    mid = l2.encode("id round trip")
    results = l2.retrieve("id round trip")
    assert results[0].memory_id == mid


# ---------------------------------------------------------------------------
# count()
# ---------------------------------------------------------------------------


def test_count_zero_on_empty_db(l2: L2EpisodicBuffer) -> None:
    assert l2.count() == 0


def test_count_increments_on_encode(l2: L2EpisodicBuffer) -> None:
    l2.encode("one")
    assert l2.count() == 1
    l2.encode("two")
    assert l2.count() == 2


def test_count_multiple_episodes(l2: L2EpisodicBuffer) -> None:
    for i in range(5):
        l2.encode(f"episode {i}")
    assert l2.count() == 5


# ---------------------------------------------------------------------------
# Persistence across restart (on-disk DB)
# ---------------------------------------------------------------------------


def test_restart_preserves_episode_in_sqlite() -> None:
    """Episodes survive closing and reopening the SQLiteStore."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")

        # First process: write an episode
        db1 = _make_db(db_path)
        l2_a = L2EpisodicBuffer(db1)
        mid = l2_a.encode("persist me across restart", event_type=EventType.TASK)
        db1.close()

        # Second process: reopen the same DB
        db2 = _make_db(db_path)
        rows = db2.query("SELECT * FROM episodes WHERE memory_id = ?", (mid,))
        assert len(rows) == 1
        assert rows[0]["content"] == "persist me across restart"
        db2.close()


def test_restart_retrieve_finds_persisted_content() -> None:
    """After restart, retrieve() finds content from before the restart."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")

        # First session
        db1 = _make_db(db_path)
        l2_a = L2EpisodicBuffer(db1)
        mid = l2_a.encode("Python data pipeline event")
        db1.close()

        # Second session — no pre-existing vector store; must rebuild from DB
        db2 = _make_db(db_path)
        l2_b = L2EpisodicBuffer(db2)
        results = l2_b.retrieve("Python data pipeline", top_k=5)
        db2.close()

        ids = [r.memory_id for r in results]
        assert mid in ids


def test_restart_count_preserved() -> None:
    """Episode count in SQLite is unchanged after restart."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")

        db1 = _make_db(db_path)
        l2_a = L2EpisodicBuffer(db1)
        for i in range(4):
            l2_a.encode(f"event {i}")
        db1.close()

        db2 = _make_db(db_path)
        l2_b = L2EpisodicBuffer(db2)
        assert l2_b.count() == 4
        db2.close()


def test_restart_multiple_episodes_all_retrievable() -> None:
    """All episodes encoded before restart are retrievable afterwards."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")

        db1 = _make_db(db_path)
        l2_a = L2EpisodicBuffer(db1)
        texts = ["alpha beta gamma", "delta epsilon zeta", "theta iota kappa"]
        mids = [l2_a.encode(t) for t in texts]
        db1.close()

        db2 = _make_db(db_path)
        l2_b = L2EpisodicBuffer(db2)
        for mid, text in zip(mids, texts):
            results = l2_b.retrieve(text, top_k=5)
            found = [r.memory_id for r in results]
            assert mid in found, f"Expected {mid!r} in results for query {text!r}"
        db2.close()


# ---------------------------------------------------------------------------
# Determinism — vector store ordering is stable across calls
# ---------------------------------------------------------------------------


def test_retrieve_is_deterministic(l2: L2EpisodicBuffer) -> None:
    """Same query on same store contents must return same order."""
    l2.encode("Python scripting language")
    l2.encode("Python machine learning")
    l2.encode("Java enterprise backend")

    r1 = [r.memory_id for r in l2.retrieve("Python", top_k=5)]
    r2 = [r.memory_id for r in l2.retrieve("Python", top_k=5)]
    assert r1 == r2


# ---------------------------------------------------------------------------
# Isolation — multiple L2 instances on separate DBs are independent
# ---------------------------------------------------------------------------


def test_two_l2_instances_are_independent() -> None:
    db_a = _make_db()
    db_b = _make_db()
    l2_a = L2EpisodicBuffer(db_a)
    l2_b = L2EpisodicBuffer(db_b)

    l2_a.encode("only in A")
    assert l2_a.count() == 1
    assert l2_b.count() == 0

    results_b = l2_b.retrieve("only in A")
    assert results_b == []

    db_a.close()
    db_b.close()


# ---------------------------------------------------------------------------
# Custom default_importance constructor parameter
# ---------------------------------------------------------------------------


def test_custom_default_importance_applied(db: SQLiteStore) -> None:
    l2 = L2EpisodicBuffer(db, default_importance=0.8)
    mid = l2.encode("custom default importance")
    rows = db.query("SELECT importance FROM memory_index WHERE id = ?", (mid,))
    assert rows[0]["importance"] == pytest.approx(0.8)


def test_explicit_importance_overrides_default(db: SQLiteStore) -> None:
    l2 = L2EpisodicBuffer(db, default_importance=0.3)
    mid = l2.encode("override importance", importance=0.7)
    rows = db.query("SELECT importance FROM memory_index WHERE id = ?", (mid,))
    assert rows[0]["importance"] == pytest.approx(0.7)
