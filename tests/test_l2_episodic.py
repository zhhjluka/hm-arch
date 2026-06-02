"""Tests for L2EpisodicBuffer.

Coverage
--------
* encode() returns a non-empty string memory_id.
* encode() persists a row to memory_index with layer=2 and status='active'.
* encode() persists a row to episodes linked to memory_index.
* encode() upserts content into the vector store (retrieve works afterwards).
* Multiple encodes produce unique memory_ids.
* Event type is stored correctly (enum value and plain string).
* Custom importance / initial_strength are stored.
* Custom metadata is serialised to memory_index.metadata (JSON).
* retrieve() returns LayerItem objects with layer=2.
* retrieve() returns items ordered by vector relevance (most relevant first).
* retrieve() respects top_k.
* retrieve() returns empty list on an empty store.
* retrieve() includes retention metadata in LayerItem.metadata.
* retrieve() includes relevance score in LayerItem.metadata.
* retrieve() excludes soft-deleted episodes.
* snapshot() returns all active episodes oldest-to-newest.
* snapshot() respects the optional limit parameter.
* snapshot() returns an empty list on an empty store.
* size property matches the number of active episodes.
* clear() soft-deletes active episodes (size becomes 0).
* clear() prevents soft-deleted items from appearing in retrieve/snapshot.
* After clear(), new encodes work normally.
* DB restart: closing and reopening the SQLiteStore preserves encoded content.
* DB restart: retrieve() after restart finds previously encoded episodes.
* DB restart: snapshot() after restart returns the same items.
* CJK content is stored and retrieved correctly.
* L2 episodes do not interfere with memory_index rows from other layers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hm_arch.layers import L2EpisodicBuffer, LayerItem
from hm_arch.storage.sqlite import SQLiteStore
from hm_arch.storage.vector import LocalVectorStore
from hm_arch.types import EventType


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_store(path: str | Path) -> SQLiteStore:
    """Open, connect, and initialise a SQLiteStore at *path*."""
    store = SQLiteStore(path)
    store.connect()
    store.initialize_schema()
    return store


@pytest.fixture()
def mem_store() -> SQLiteStore:
    """In-memory SQLiteStore, connected and schema-initialised."""
    return _make_store(":memory:")


@pytest.fixture()
def l2(mem_store: SQLiteStore) -> L2EpisodicBuffer:
    """L2EpisodicBuffer backed by an in-memory store."""
    return L2EpisodicBuffer(mem_store)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_layer_index_is_two(self, l2: L2EpisodicBuffer) -> None:
        assert L2EpisodicBuffer.LAYER_INDEX == 2
        assert l2.LAYER_INDEX == 2

    def test_default_vector_store_is_local(self, mem_store: SQLiteStore) -> None:
        buf = L2EpisodicBuffer(mem_store)
        assert isinstance(buf._vector, LocalVectorStore)

    def test_custom_vector_store_is_used(self, mem_store: SQLiteStore) -> None:
        vs = LocalVectorStore()
        buf = L2EpisodicBuffer(mem_store, vector_store=vs)
        assert buf._vector is vs

    def test_empty_on_fresh_store(self, l2: L2EpisodicBuffer) -> None:
        assert l2.size == 0

    def test_importable_from_layers_package(self) -> None:
        from hm_arch.layers import L2EpisodicBuffer as L2  # noqa: F401

        assert L2 is not None


# ---------------------------------------------------------------------------
# encode() — persistence acceptance criteria
# ---------------------------------------------------------------------------


class TestEncode:
    def test_returns_string_id(self, l2: L2EpisodicBuffer) -> None:
        mid = l2.encode("hello world")
        assert isinstance(mid, str)
        assert len(mid) > 0

    def test_unique_ids_per_call(self, l2: L2EpisodicBuffer) -> None:
        ids = {l2.encode(f"event {i}") for i in range(10)}
        assert len(ids) == 10

    def test_persists_memory_index_row(
        self, l2: L2EpisodicBuffer, mem_store: SQLiteStore
    ) -> None:
        mid = l2.encode("test content")
        rows = mem_store.query(
            "SELECT * FROM memory_index WHERE id = ?", (mid,)
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["layer"] == 2
        assert row["status"] == "active"

    def test_memory_index_importance(
        self, l2: L2EpisodicBuffer, mem_store: SQLiteStore
    ) -> None:
        mid = l2.encode("important event", importance=0.9)
        rows = mem_store.query(
            "SELECT importance FROM memory_index WHERE id = ?", (mid,)
        )
        assert abs(rows[0]["importance"] - 0.9) < 1e-9

    def test_memory_index_initial_strength(
        self, l2: L2EpisodicBuffer, mem_store: SQLiteStore
    ) -> None:
        mid = l2.encode("test", initial_strength=0.75)
        rows = mem_store.query(
            "SELECT initial_strength FROM memory_index WHERE id = ?", (mid,)
        )
        assert abs(rows[0]["initial_strength"] - 0.75) < 1e-9

    def test_memory_index_current_retention_starts_at_one(
        self, l2: L2EpisodicBuffer, mem_store: SQLiteStore
    ) -> None:
        mid = l2.encode("new memory")
        rows = mem_store.query(
            "SELECT current_retention FROM memory_index WHERE id = ?", (mid,)
        )
        assert abs(rows[0]["current_retention"] - 1.0) < 1e-9

    def test_persists_episode_row(
        self, l2: L2EpisodicBuffer, mem_store: SQLiteStore
    ) -> None:
        mid = l2.encode("episode content", event_type=EventType.CONVERSATION)
        rows = mem_store.query(
            "SELECT * FROM episodes WHERE memory_id = ?", (mid,)
        )
        assert len(rows) == 1
        assert rows[0]["content"] == "episode content"
        assert rows[0]["event_type"] == "conversation"

    def test_event_type_enum_stored_as_value(
        self, l2: L2EpisodicBuffer, mem_store: SQLiteStore
    ) -> None:
        for et in EventType:
            mid = l2.encode(f"event {et.value}", event_type=et)
            rows = mem_store.query(
                "SELECT event_type FROM episodes WHERE memory_id = ?", (mid,)
            )
            assert rows[0]["event_type"] == et.value

    def test_event_type_plain_string(
        self, l2: L2EpisodicBuffer, mem_store: SQLiteStore
    ) -> None:
        mid = l2.encode("plain string event type", event_type="custom_type")
        rows = mem_store.query(
            "SELECT event_type FROM episodes WHERE memory_id = ?", (mid,)
        )
        assert rows[0]["event_type"] == "custom_type"

    def test_default_event_type_is_observation(
        self, l2: L2EpisodicBuffer, mem_store: SQLiteStore
    ) -> None:
        mid = l2.encode("default event type")
        rows = mem_store.query(
            "SELECT event_type FROM episodes WHERE memory_id = ?", (mid,)
        )
        assert rows[0]["event_type"] == "observation"

    def test_metadata_stored_as_json(
        self, l2: L2EpisodicBuffer, mem_store: SQLiteStore
    ) -> None:
        import json

        mid = l2.encode("meta test", metadata={"source": "agent", "priority": 3})
        rows = mem_store.query(
            "SELECT metadata FROM memory_index WHERE id = ?", (mid,)
        )
        stored = json.loads(rows[0]["metadata"])
        assert stored == {"source": "agent", "priority": 3}

    def test_none_metadata_stores_empty_dict(
        self, l2: L2EpisodicBuffer, mem_store: SQLiteStore
    ) -> None:
        import json

        mid = l2.encode("no metadata")
        rows = mem_store.query(
            "SELECT metadata FROM memory_index WHERE id = ?", (mid,)
        )
        assert json.loads(rows[0]["metadata"]) == {}

    def test_increases_size(self, l2: L2EpisodicBuffer) -> None:
        assert l2.size == 0
        l2.encode("first")
        assert l2.size == 1
        l2.encode("second")
        assert l2.size == 2

    def test_upserts_into_vector_store(self, l2: L2EpisodicBuffer) -> None:
        """After encode, retrieve must find the content."""
        mid = l2.encode("Python is the best language for data science")
        results = l2.retrieve("Python data science")
        assert any(r.memory_id == mid for r in results)


# ---------------------------------------------------------------------------
# retrieve() — acceptance criteria
# ---------------------------------------------------------------------------


class TestRetrieve:
    def test_returns_list_of_layer_items(self, l2: L2EpisodicBuffer) -> None:
        l2.encode("test item")
        results = l2.retrieve("test")
        assert isinstance(results, list)
        assert all(isinstance(r, LayerItem) for r in results)

    def test_layer_is_two(self, l2: L2EpisodicBuffer) -> None:
        l2.encode("layer two content")
        results = l2.retrieve("layer two")
        assert results
        assert all(r.layer == 2 for r in results)

    def test_empty_store_returns_empty_list(self, l2: L2EpisodicBuffer) -> None:
        assert l2.retrieve("anything") == []

    def test_respects_top_k(self, l2: L2EpisodicBuffer) -> None:
        for i in range(10):
            l2.encode(f"Python item {i} programming language")
        results = l2.retrieve("Python programming", top_k=3)
        assert len(results) <= 3

    def test_most_relevant_first(self, l2: L2EpisodicBuffer) -> None:
        l2.encode("Java enterprise backend server")
        l2.encode("Python quick scripting automation")
        mid_best = l2.encode("Python machine learning deep learning neural networks")
        results = l2.retrieve("Python machine learning deep", top_k=3)
        assert results[0].memory_id == mid_best

    def test_result_content_matches_encoded(self, l2: L2EpisodicBuffer) -> None:
        content = "The user prefers Python over Java"
        mid = l2.encode(content)
        results = l2.retrieve("user Python Java", top_k=1)
        assert results
        assert results[0].content == content
        assert results[0].memory_id == mid

    def test_result_has_retention_metadata(self, l2: L2EpisodicBuffer) -> None:
        l2.encode("retention metadata test")
        results = l2.retrieve("retention metadata")
        assert results
        assert "retention" in results[0].metadata
        assert isinstance(results[0].metadata["retention"], float)

    def test_result_has_importance_metadata(self, l2: L2EpisodicBuffer) -> None:
        l2.encode("importance test", importance=0.8)
        results = l2.retrieve("importance test")
        assert results
        assert abs(results[0].metadata["importance"] - 0.8) < 1e-9

    def test_result_has_event_type_metadata(self, l2: L2EpisodicBuffer) -> None:
        l2.encode("event type test", event_type=EventType.CODE)
        results = l2.retrieve("event type test")
        assert results
        assert results[0].metadata["event_type"] == "code"

    def test_result_has_relevance_score(self, l2: L2EpisodicBuffer) -> None:
        l2.encode("relevance score check")
        results = l2.retrieve("relevance score")
        assert results
        assert "relevance" in results[0].metadata
        score = results[0].metadata["relevance"]
        assert 0.0 <= score <= 1.0

    def test_added_at_is_datetime(self, l2: L2EpisodicBuffer) -> None:
        from datetime import datetime

        l2.encode("datetime check")
        results = l2.retrieve("datetime check")
        assert results
        assert isinstance(results[0].added_at, datetime)
        assert results[0].added_at.tzinfo is not None

    def test_top_k_larger_than_store(self, l2: L2EpisodicBuffer) -> None:
        l2.encode("only item")
        results = l2.retrieve("only item", top_k=100)
        assert len(results) == 1

    def test_soft_deleted_items_excluded(
        self, l2: L2EpisodicBuffer, mem_store: SQLiteStore
    ) -> None:
        mid = l2.encode("to be deleted item")
        # Manually soft-delete via SQL.
        mem_store.execute(
            "UPDATE memory_index SET status = 'deleted' WHERE id = ?", (mid,)
        )
        results = l2.retrieve("deleted item")
        assert not any(r.memory_id == mid for r in results)


# ---------------------------------------------------------------------------
# snapshot()
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_empty_store_returns_empty_list(self, l2: L2EpisodicBuffer) -> None:
        assert l2.snapshot() == []

    def test_returns_layer_items(self, l2: L2EpisodicBuffer) -> None:
        l2.encode("a")
        items = l2.snapshot()
        assert all(isinstance(it, LayerItem) for it in items)

    def test_ordered_oldest_to_newest(self, l2: L2EpisodicBuffer) -> None:
        l2.encode("first")
        l2.encode("second")
        l2.encode("third")
        contents = [it.content for it in l2.snapshot()]
        assert contents == ["first", "second", "third"]

    def test_limit_parameter(self, l2: L2EpisodicBuffer) -> None:
        for i in range(5):
            l2.encode(f"item {i}")
        items = l2.snapshot(limit=3)
        assert len(items) == 3
        assert items[0].content == "item 0"

    def test_limit_larger_than_size(self, l2: L2EpisodicBuffer) -> None:
        l2.encode("only one")
        assert len(l2.snapshot(limit=100)) == 1

    def test_snapshot_layer_is_two(self, l2: L2EpisodicBuffer) -> None:
        l2.encode("layer check")
        assert all(it.layer == 2 for it in l2.snapshot())

    def test_snapshot_excludes_soft_deleted(
        self, l2: L2EpisodicBuffer, mem_store: SQLiteStore
    ) -> None:
        mid = l2.encode("will be deleted")
        l2.encode("stays active")
        mem_store.execute(
            "UPDATE memory_index SET status = 'deleted' WHERE id = ?", (mid,)
        )
        snap = l2.snapshot()
        assert len(snap) == 1
        assert snap[0].content == "stays active"


# ---------------------------------------------------------------------------
# size property
# ---------------------------------------------------------------------------


class TestSize:
    def test_zero_initially(self, l2: L2EpisodicBuffer) -> None:
        assert l2.size == 0

    def test_increments_on_encode(self, l2: L2EpisodicBuffer) -> None:
        for i in range(5):
            assert l2.size == i
            l2.encode(f"item {i}")
        assert l2.size == 5

    def test_only_counts_active(
        self, l2: L2EpisodicBuffer, mem_store: SQLiteStore
    ) -> None:
        mid = l2.encode("to delete")
        assert l2.size == 1
        mem_store.execute(
            "UPDATE memory_index SET status = 'deleted' WHERE id = ?", (mid,)
        )
        assert l2.size == 0


# ---------------------------------------------------------------------------
# clear()
# ---------------------------------------------------------------------------


class TestClear:
    def test_size_is_zero_after_clear(self, l2: L2EpisodicBuffer) -> None:
        l2.encode("a")
        l2.encode("b")
        l2.clear()
        assert l2.size == 0

    def test_snapshot_empty_after_clear(self, l2: L2EpisodicBuffer) -> None:
        l2.encode("x")
        l2.clear()
        assert l2.snapshot() == []

    def test_retrieve_empty_after_clear(self, l2: L2EpisodicBuffer) -> None:
        l2.encode("Python programming language")
        l2.clear()
        assert l2.retrieve("Python") == []

    def test_rows_are_soft_deleted_not_removed(
        self, l2: L2EpisodicBuffer, mem_store: SQLiteStore
    ) -> None:
        mid = l2.encode("soft delete test")
        l2.clear()
        rows = mem_store.query(
            "SELECT status FROM memory_index WHERE id = ?", (mid,)
        )
        assert rows[0]["status"] == "deleted"

    def test_can_encode_after_clear(self, l2: L2EpisodicBuffer) -> None:
        l2.encode("before clear")
        l2.clear()
        mid = l2.encode("after clear")
        assert l2.size == 1
        results = l2.retrieve("after clear")
        assert results[0].memory_id == mid


# ---------------------------------------------------------------------------
# DB restart — persistence acceptance criteria
# ---------------------------------------------------------------------------


class TestDBRestart:
    def test_encode_persists_across_restart(self, tmp_path: Path) -> None:
        """Closing and reopening the DB preserves the encoded episode."""
        db_path = tmp_path / "memory.db"

        # First session: encode an episode.
        store1 = _make_store(db_path)
        l2_session1 = L2EpisodicBuffer(store1)
        mid = l2_session1.encode(
            "The user prefers Python over Java",
            event_type=EventType.CONVERSATION,
        )
        store1.close()

        # Second session: open the same DB with a fresh L2 instance.
        store2 = _make_store(db_path)
        l2_session2 = L2EpisodicBuffer(store2)

        rows = store2.query(
            "SELECT * FROM memory_index WHERE id = ?", (mid,)
        )
        assert len(rows) == 1
        assert rows[0]["layer"] == 2
        assert rows[0]["status"] == "active"
        store2.close()

    def test_retrieve_works_after_restart(self, tmp_path: Path) -> None:
        """retrieve() finds previously encoded episodes after a DB restart."""
        db_path = tmp_path / "memory.db"

        store1 = _make_store(db_path)
        mid = L2EpisodicBuffer(store1).encode(
            "Python is the best language for data science"
        )
        store1.close()

        store2 = _make_store(db_path)
        l2 = L2EpisodicBuffer(store2)
        results = l2.retrieve("Python data science")
        assert any(r.memory_id == mid for r in results)
        store2.close()

    def test_snapshot_works_after_restart(self, tmp_path: Path) -> None:
        """snapshot() returns persisted items after a DB restart."""
        db_path = tmp_path / "memory.db"
        contents = ["first event", "second event", "third event"]

        store1 = _make_store(db_path)
        l2_s1 = L2EpisodicBuffer(store1)
        for c in contents:
            l2_s1.encode(c)
        store1.close()

        store2 = _make_store(db_path)
        l2_s2 = L2EpisodicBuffer(store2)
        snap = l2_s2.snapshot()
        stored_contents = [it.content for it in snap]
        for c in contents:
            assert c in stored_contents
        store2.close()

    def test_size_after_restart(self, tmp_path: Path) -> None:
        """size property reflects persisted episode count after restart."""
        db_path = tmp_path / "memory.db"

        store1 = _make_store(db_path)
        l2_s1 = L2EpisodicBuffer(store1)
        for i in range(3):
            l2_s1.encode(f"event {i}")
        store1.close()

        store2 = _make_store(db_path)
        l2_s2 = L2EpisodicBuffer(store2)
        assert l2_s2.size == 3
        store2.close()

    def test_multiple_restart_cycles(self, tmp_path: Path) -> None:
        """Content survives multiple open/close cycles."""
        db_path = tmp_path / "memory.db"

        store1 = _make_store(db_path)
        mid = L2EpisodicBuffer(store1).encode("survived multiple restarts")
        store1.close()

        for _ in range(3):
            s = _make_store(db_path)
            l2 = L2EpisodicBuffer(s)
            results = l2.retrieve("survived multiple restarts")
            assert any(r.memory_id == mid for r in results)
            s.close()

    def test_hydrate_does_not_duplicate_entries(self, tmp_path: Path) -> None:
        """Opening the same DB twice in one process doesn't double the vector index."""
        db_path = tmp_path / "memory.db"

        store1 = _make_store(db_path)
        l2_a = L2EpisodicBuffer(store1)
        l2_a.encode("unique item for dedup test")
        # Open a second L2 against the same store — _hydrate_from_db runs again.
        l2_b = L2EpisodicBuffer(store1)
        # LocalVectorStore uses upsert so duplicates are overwritten, not appended.
        results = l2_b.retrieve("unique item dedup")
        # Should still be exactly one result per encoded item.
        mids = [r.memory_id for r in results]
        assert len(mids) == len(set(mids))
        store1.close()


# ---------------------------------------------------------------------------
# CJK content
# ---------------------------------------------------------------------------


class TestCJKContent:
    def test_cjk_encode_and_retrieve(self, l2: L2EpisodicBuffer) -> None:
        mid = l2.encode("用户偏好 Python 编程语言")
        results = l2.retrieve("用户 Python")
        assert any(r.memory_id == mid for r in results)

    def test_cjk_snapshot_content(self, l2: L2EpisodicBuffer) -> None:
        content = "机器学习模型训练"
        l2.encode(content)
        snap = l2.snapshot()
        assert snap[0].content == content


# ---------------------------------------------------------------------------
# Layer isolation
# ---------------------------------------------------------------------------


class TestLayerIsolation:
    def test_l2_does_not_count_other_layers(
        self, mem_store: SQLiteStore
    ) -> None:
        """Rows from other layers must not inflate L2 size."""
        import json
        from datetime import datetime, timezone

        now = datetime.now(tz=timezone.utc).isoformat()
        # Manually insert a layer-1 row.
        mem_store.execute(
            """INSERT INTO memory_index
               (id, layer, created_at, updated_at, importance, initial_strength,
                current_retention, status, tags, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("l1_fake", 1, now, now, 0.5, 0.5, 1.0, "active", "[]", "{}"),
        )
        l2 = L2EpisodicBuffer(mem_store)
        assert l2.size == 0

    def test_l2_snapshot_excludes_other_layers(
        self, mem_store: SQLiteStore
    ) -> None:
        """snapshot() must only return L2 items."""
        import json
        from datetime import datetime, timezone

        now = datetime.now(tz=timezone.utc).isoformat()
        mem_store.execute(
            """INSERT INTO memory_index
               (id, layer, created_at, updated_at, importance, initial_strength,
                current_retention, status, tags, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("l1_fake", 1, now, now, 0.5, 0.5, 1.0, "active", "[]", "{}"),
        )
        l2 = L2EpisodicBuffer(mem_store)
        l2.encode("actual L2 item")
        snap = l2.snapshot()
        assert len(snap) == 1
        assert snap[0].content == "actual L2 item"
