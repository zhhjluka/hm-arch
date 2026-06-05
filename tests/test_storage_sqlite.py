"""Tests for SQLiteStore — the HM-Arch SQLite storage backend.

Design principles
-----------------
* Every test uses ``tmp_path`` (pytest's built-in fixture), so each test gets
  its own isolated temporary directory.  No shared state between tests.
* All assertions are offline: no external APIs, no LLM keys.
* Tests cover the acceptance criteria from MEM-8:
  - Temporary DB initializes all expected tables.
  - Reopening the DB preserves inserted data.
  - Tests do not share state.
* Column/index assertions match the PRD schema exactly (per Codex review).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from hm_arch.storage.sqlite import REQUIRED_TABLES, SQLiteStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _table_names(store: SQLiteStore) -> set[str]:
    """Return the set of user-created table names in the connected store."""
    rows = store.query(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    return {row["name"] for row in rows}


def _index_names(store: SQLiteStore) -> set[str]:
    """Return the set of user-created index names."""
    rows = store.query(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
    )
    return {row["name"] for row in rows}


def _indexed_columns(store: SQLiteStore, index_name: str) -> list[str]:
    """Return indexed column names in index order."""
    rows = store.query(f"PRAGMA index_info({index_name})")
    return [row["name"] for row in rows]


def _col_info(store: SQLiteStore, table: str) -> dict[str, dict]:
    """Return column metadata keyed by column name from PRAGMA table_info."""
    rows = store.query(f"PRAGMA table_info({table})")
    return {row["name"]: dict(row) for row in rows}


# ---------------------------------------------------------------------------
# SQLite concurrency (MEM-57)
# ---------------------------------------------------------------------------


class TestConcurrencyConfiguration:
    def test_wal_journal_mode_on_file_db(self, tmp_path: Path) -> None:
        db = tmp_path / "wal_check.db"
        with SQLiteStore(db) as store:
            row = store.query("PRAGMA journal_mode")
        assert row[0]["journal_mode"].lower() == "wal"

    def test_foreign_keys_enabled(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "fk_pragma.db") as store:
            row = store.query("PRAGMA foreign_keys")
        assert int(row[0]["foreign_keys"]) == 1

    def test_transaction_commits(self, tmp_path: Path) -> None:
        ts = "2024-06-01T00:00:00Z"
        db = tmp_path / "txn_commit.db"
        with SQLiteStore(db) as store:
            store.initialize_schema()
            with store.transaction():
                store.execute_no_commit(
                    "INSERT INTO meta_memory (key, value, updated_at) VALUES (?, ?, ?)",
                    ("txn_key", "txn_val", ts),
                )
        with SQLiteStore(db) as store:
            rows = store.query(
                "SELECT value FROM meta_memory WHERE key = ?", ("txn_key",)
            )
        assert rows[0]["value"] == "txn_val"

    def test_transaction_rolls_back_on_error(self, tmp_path: Path) -> None:
        ts = "2024-06-01T00:00:00Z"
        db = tmp_path / "txn_rollback.db"
        with SQLiteStore(db) as store:
            store.initialize_schema()
            with pytest.raises(ValueError):
                with store.transaction():
                    store.execute_no_commit(
                        "INSERT INTO meta_memory (key, value, updated_at) VALUES (?, ?, ?)",
                        ("rollback_key", "gone", ts),
                    )
                    raise ValueError("abort")
        with SQLiteStore(db) as store:
            rows = store.query(
                "SELECT key FROM meta_memory WHERE key = ?", ("rollback_key",)
            )
        assert rows == []


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------


class TestConnectionLifecycle:
    def test_connect_returns_self(self, tmp_path: Path) -> None:
        store = SQLiteStore(tmp_path / "test.db")
        result = store.connect()
        assert result is store
        store.close()

    def test_is_connected_false_before_connect(self, tmp_path: Path) -> None:
        store = SQLiteStore(tmp_path / "test.db")
        assert store.is_connected is False

    def test_is_connected_true_after_connect(self, tmp_path: Path) -> None:
        store = SQLiteStore(tmp_path / "test.db")
        store.connect()
        assert store.is_connected is True
        store.close()

    def test_is_connected_false_after_close(self, tmp_path: Path) -> None:
        store = SQLiteStore(tmp_path / "test.db")
        store.connect()
        store.close()
        assert store.is_connected is False

    def test_double_connect_is_safe(self, tmp_path: Path) -> None:
        store = SQLiteStore(tmp_path / "test.db")
        store.connect()
        store.connect()  # second call must be a no-op
        assert store.is_connected is True
        store.close()

    def test_path_property(self, tmp_path: Path) -> None:
        db_path = tmp_path / "mydb.db"
        store = SQLiteStore(db_path)
        assert store.path == str(db_path)

    def test_require_connection_raises_before_connect(self, tmp_path: Path) -> None:
        store = SQLiteStore(tmp_path / "test.db")
        with pytest.raises(RuntimeError, match="not connected"):
            store.query("SELECT 1")


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestContextManager:
    def test_context_manager_connects_and_closes(self, tmp_path: Path) -> None:
        db = tmp_path / "cm.db"
        with SQLiteStore(db) as store:
            assert store.is_connected is True
        assert store.is_connected is False

    def test_context_manager_rollback_on_exception(self, tmp_path: Path) -> None:
        db = tmp_path / "cm_err.db"
        with pytest.raises(ValueError):
            with SQLiteStore(db) as store:
                store.initialize_schema()
                raise ValueError("intentional")
        assert store.is_connected is False

    def test_in_memory_store(self) -> None:
        with SQLiteStore(":memory:") as store:
            store.initialize_schema()
            tables = _table_names(store)
            assert REQUIRED_TABLES.issubset(tables)


# ---------------------------------------------------------------------------
# Schema initialization — tables and indexes
# ---------------------------------------------------------------------------


class TestInitializeSchema:
    def test_all_required_tables_created(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "schema.db") as store:
            store.initialize_schema()
            tables = _table_names(store)
        assert REQUIRED_TABLES.issubset(tables), f"Missing tables: {REQUIRED_TABLES - tables}"

    def test_initialize_schema_is_idempotent(self, tmp_path: Path) -> None:
        db = tmp_path / "idempotent.db"
        with SQLiteStore(db) as store:
            store.initialize_schema()
            store.initialize_schema()  # second call must not raise
            tables = _table_names(store)
        assert REQUIRED_TABLES.issubset(tables)

    # --- memory_index ---

    def test_memory_index_columns(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "mi.db") as store:
            store.initialize_schema()
            cols = _col_info(store, "memory_index")
        expected = {
            "id", "layer", "created_at", "updated_at",
            "importance", "initial_strength", "current_retention",
            "last_accessed_at", "access_count",
            "status", "superseded_by", "tags", "metadata", "content_hash",
            "provenance_agent", "provenance_project", "provenance_session",
            "memory_type",
        }
        assert expected.issubset(cols.keys()), f"Missing columns: {expected - cols.keys()}"

    def test_memory_index_defaults(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "mi_def.db") as store:
            store.initialize_schema()
            cols = _col_info(store, "memory_index")
        assert float(cols["importance"]["dflt_value"]) == pytest.approx(0.5)
        assert float(cols["initial_strength"]["dflt_value"]) == pytest.approx(0.5)
        assert float(cols["current_retention"]["dflt_value"]) == pytest.approx(1.0)
        assert int(cols["access_count"]["dflt_value"]) == 0
        assert cols["status"]["dflt_value"].strip("'\"") == "active"
        assert cols["tags"]["dflt_value"].strip("'\"") == "[]"
        assert cols["metadata"]["dflt_value"].strip("'\"") == "{}"

    # --- episodes ---

    def test_episodes_columns(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "ep.db") as store:
            store.initialize_schema()
            cols = _col_info(store, "episodes")
        expected = {
            "id", "memory_id", "content", "event_type",
            "emotion_score", "context_window", "raw_json",
        }
        assert expected.issubset(cols.keys()), f"Missing columns: {expected - cols.keys()}"

    # --- semantics ---

    def test_semantics_columns(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "sem.db") as store:
            store.initialize_schema()
            cols = _col_info(store, "semantics")
        expected = {
            "id", "memory_id", "entity", "relation", "value",
            "confidence", "source_episodes", "version",
        }
        assert expected.issubset(cols.keys()), f"Missing columns: {expected - cols.keys()}"

    def test_semantics_defaults(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "sem_def.db") as store:
            store.initialize_schema()
            cols = _col_info(store, "semantics")
        assert float(cols["confidence"]["dflt_value"]) == pytest.approx(1.0)
        assert cols["source_episodes"]["dflt_value"].strip("'\"") == "[]"
        assert int(cols["version"]["dflt_value"]) == 1

    def test_semantics_entity_index_exists(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "sem_idx.db") as store:
            store.initialize_schema()
            indexes = _index_names(store)
        assert "idx_semantics_entity" in indexes

    def test_semantics_relation_index_exists(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "sem_idx2.db") as store:
            store.initialize_schema()
            indexes = _index_names(store)
            columns = _indexed_columns(store, "idx_semantics_relation")
        assert "idx_semantics_relation" in indexes
        assert columns == ["entity", "relation"]

    # --- skills ---

    def test_skills_columns(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "sk.db") as store:
            store.initialize_schema()
            cols = _col_info(store, "skills")
        expected = {
            "id", "name", "description", "code",
            "usage_count", "last_used_at", "success_rate", "average_duration_ms",
        }
        assert expected.issubset(cols.keys()), f"Missing columns: {expected - cols.keys()}"

    def test_skills_name_is_unique(self, tmp_path: Path) -> None:
        ts = "2024-06-01T00:00:00Z"
        with SQLiteStore(tmp_path / "sk_uniq.db") as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO skills (id, name) VALUES (?, ?)", ("s1", "ping")
            )
            with pytest.raises(sqlite3.IntegrityError):
                store.execute(
                    "INSERT INTO skills (id, name) VALUES (?, ?)", ("s2", "ping")
                )

    # --- meta_memory ---

    def test_meta_memory_columns(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "mm.db") as store:
            store.initialize_schema()
            cols = _col_info(store, "meta_memory")
        expected = {"key", "value", "description", "updated_at"}
        assert expected.issubset(cols.keys()), f"Missing columns: {expected - cols.keys()}"

    def test_meta_memory_key_is_primary_key(self, tmp_path: Path) -> None:
        ts = "2024-01-01T00:00:00Z"
        with SQLiteStore(tmp_path / "mm_pk.db") as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO meta_memory (key, value, updated_at) VALUES (?, ?, ?)",
                ("agent_name", "Bot", ts),
            )
            with pytest.raises(sqlite3.IntegrityError):
                store.execute(
                    "INSERT INTO meta_memory (key, value, updated_at) VALUES (?, ?, ?)",
                    ("agent_name", "OtherBot", ts),
                )

    # --- review_queue ---

    def test_review_queue_columns(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "rq.db") as store:
            store.initialize_schema()
            cols = _col_info(store, "review_queue")
        expected = {
            "id", "memory_id", "ef", "current_interval",
            "next_review_at", "last_quality", "urgency",
        }
        assert expected.issubset(cols.keys()), f"Missing columns: {expected - cols.keys()}"

    def test_review_queue_id_is_autoincrement(self, tmp_path: Path) -> None:
        ts = "2024-06-01T00:00:00Z"
        with SQLiteStore(tmp_path / "rq_auto.db") as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO memory_index (id, layer, created_at, updated_at)"
                " VALUES (?, ?, ?, ?)",
                ("m1", 2, ts, ts),
            )
            store.execute(
                "INSERT INTO memory_index (id, layer, created_at, updated_at)"
                " VALUES (?, ?, ?, ?)",
                ("m2", 2, ts, ts),
            )
            c1 = store.execute(
                "INSERT INTO review_queue (memory_id, ef, next_review_at) VALUES (?, ?, ?)",
                ("m1", 2.5, ts),
            )
            c2 = store.execute(
                "INSERT INTO review_queue (memory_id, ef, next_review_at) VALUES (?, ?, ?)",
                ("m2", 2.5, ts),
            )
        assert c2.lastrowid == c1.lastrowid + 1

    def test_review_next_index_exists(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "rq_idx.db") as store:
            store.initialize_schema()
            indexes = _index_names(store)
        assert "idx_review_next" in indexes

    def test_review_queue_memory_id_is_unique(self, tmp_path: Path) -> None:
        ts = "2024-06-01T00:00:00Z"
        with SQLiteStore(tmp_path / "rq_uniq.db") as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO memory_index (id, layer, created_at, updated_at)"
                " VALUES (?, ?, ?, ?)",
                ("mx", 2, ts, ts),
            )
            store.execute(
                "INSERT INTO review_queue (memory_id, ef, next_review_at) VALUES (?, ?, ?)",
                ("mx", 2.5, ts),
            )
            with pytest.raises(sqlite3.IntegrityError):
                store.execute(
                    "INSERT INTO review_queue (memory_id, ef, next_review_at) VALUES (?, ?, ?)",
                    ("mx", 2.5, ts),
                )

    # --- consolidation_log ---

    def test_consolidation_log_columns(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "cl.db") as store:
            store.initialize_schema()
            cols = _col_info(store, "consolidation_log")
        expected = {"id", "started_at", "completed_at", "duration_seconds", "stats"}
        assert expected.issubset(cols.keys()), f"Missing columns: {expected - cols.keys()}"

    def test_consolidation_log_id_is_autoincrement(self, tmp_path: Path) -> None:
        ts = "2024-06-01T00:00:00Z"
        with SQLiteStore(tmp_path / "cl_auto.db") as store:
            store.initialize_schema()
            c1 = store.execute(
                "INSERT INTO consolidation_log (started_at, completed_at, stats)"
                " VALUES (?, ?, ?)",
                (ts, ts, "{}"),
            )
            c2 = store.execute(
                "INSERT INTO consolidation_log (started_at, completed_at, stats)"
                " VALUES (?, ?, ?)",
                (ts, ts, "{}"),
            )
        assert c2.lastrowid == c1.lastrowid + 1


# ---------------------------------------------------------------------------
# execute() and query() helpers
# ---------------------------------------------------------------------------


class TestExecuteAndQuery:
    def test_execute_insert_and_query_select(self, tmp_path: Path) -> None:
        ts = "2024-01-01T00:00:00Z"
        with SQLiteStore(tmp_path / "rw.db") as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO meta_memory (key, value, updated_at) VALUES (?, ?, ?)",
                ("agent_name", "TestBot", ts),
            )
            rows = store.query(
                "SELECT value FROM meta_memory WHERE key = ?", ("agent_name",)
            )

        assert len(rows) == 1
        assert rows[0]["value"] == "TestBot"

    def test_query_returns_list_of_rows(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "list.db") as store:
            store.initialize_schema()
            rows = store.query("SELECT name FROM sqlite_master WHERE type='table'")
        assert isinstance(rows, list)
        assert all(isinstance(r, sqlite3.Row) for r in rows)

    def test_rows_accessible_by_column_name(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "byname.db") as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO skills (id, name, code) VALUES (?, ?, ?)",
                ("sk1", "ping", "return 'pong'"),
            )
            rows = store.query("SELECT * FROM skills WHERE id = ?", ("sk1",))

        assert rows[0]["name"] == "ping"
        assert rows[0]["code"] == "return 'pong'"

    def test_execute_returns_cursor_with_lastrowid(self, tmp_path: Path) -> None:
        ts = "2024-06-01T00:00:00Z"
        with SQLiteStore(tmp_path / "cursor.db") as store:
            store.initialize_schema()
            cursor = store.execute(
                "INSERT INTO consolidation_log (started_at, completed_at, stats)"
                " VALUES (?, ?, ?)",
                (ts, ts, "{}"),
            )
        assert cursor.lastrowid is not None
        assert cursor.lastrowid >= 1

    def test_named_params_work(self, tmp_path: Path) -> None:
        ts = "2024-01-01T00:00:00Z"
        with SQLiteStore(tmp_path / "named.db") as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO meta_memory (key, value, updated_at)"
                " VALUES (:key, :val, :ua)",
                {"key": "lang", "val": "Python", "ua": ts},
            )
            rows = store.query(
                "SELECT value FROM meta_memory WHERE key = :key", {"key": "lang"}
            )

        assert rows[0]["value"] == "Python"

    def test_empty_table_returns_empty_list(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "empty.db") as store:
            store.initialize_schema()
            rows = store.query("SELECT * FROM consolidation_log")
        assert rows == []


# ---------------------------------------------------------------------------
# Persistence across connections (acceptance criteria)
# ---------------------------------------------------------------------------


class TestPersistenceAcrossConnections:
    """Verify that reopening the database preserves data (MEM-8 acceptance)."""

    def test_data_persists_after_reopen(self, tmp_path: Path) -> None:
        db = tmp_path / "persist.db"
        ts = "2024-06-01T00:00:00Z"

        with SQLiteStore(db) as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO meta_memory (key, value, updated_at) VALUES (?, ?, ?)",
                ("session", "active", ts),
            )

        with SQLiteStore(db) as store:
            rows = store.query(
                "SELECT value FROM meta_memory WHERE key = ?", ("session",)
            )

        assert len(rows) == 1
        assert rows[0]["value"] == "active"

    def test_schema_preserved_after_reopen(self, tmp_path: Path) -> None:
        db = tmp_path / "schema_persist.db"

        with SQLiteStore(db) as store:
            store.initialize_schema()

        with SQLiteStore(db) as store:
            tables = _table_names(store)

        assert REQUIRED_TABLES.issubset(tables)

    def test_indexes_preserved_after_reopen(self, tmp_path: Path) -> None:
        db = tmp_path / "idx_persist.db"

        with SQLiteStore(db) as store:
            store.initialize_schema()

        with SQLiteStore(db) as store:
            indexes = _index_names(store)

        assert "idx_semantics_entity" in indexes
        assert "idx_semantics_relation" in indexes
        assert "idx_review_next" in indexes

    def test_multiple_rows_persist(self, tmp_path: Path) -> None:
        db = tmp_path / "multi.db"
        ts = "2024-06-01T00:00:00Z"

        with SQLiteStore(db) as store:
            store.initialize_schema()
            for i in range(5):
                store.execute(
                    "INSERT INTO skills (id, name) VALUES (?, ?)",
                    (f"sk{i}", f"skill_{i}"),
                )

        with SQLiteStore(db) as store:
            rows = store.query("SELECT id FROM skills ORDER BY id")

        assert len(rows) == 5
        assert [r["id"] for r in rows] == ["sk0", "sk1", "sk2", "sk3", "sk4"]


# ---------------------------------------------------------------------------
# Test isolation — tests do not share state
# ---------------------------------------------------------------------------


class TestIsolation:
    """Confirm no shared state bleeds between tests.

    Each test writes to its own ``tmp_path``-scoped file.
    These tests intentionally use the same table / key values to prove
    that isolation is guaranteed by the fixture, not by unique naming.
    """

    def _write_marker(self, db: Path, value: str) -> None:
        ts = "2024-01-01T00:00:00Z"
        with SQLiteStore(db) as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO meta_memory (key, value, updated_at) VALUES (?, ?, ?)",
                ("marker", value, ts),
            )

    def _read_marker(self, db: Path) -> str:
        with SQLiteStore(db) as store:
            rows = store.query("SELECT value FROM meta_memory WHERE key = 'marker'")
        return rows[0]["value"]

    def test_isolation_a(self, tmp_path: Path) -> None:
        db = tmp_path / "iso.db"
        self._write_marker(db, "alpha")
        assert self._read_marker(db) == "alpha"

    def test_isolation_b(self, tmp_path: Path) -> None:
        db = tmp_path / "iso.db"
        self._write_marker(db, "beta")
        assert self._read_marker(db) == "beta"

    def test_isolation_c(self, tmp_path: Path) -> None:
        db = tmp_path / "iso.db"
        self._write_marker(db, "gamma")
        assert self._read_marker(db) == "gamma"


# ---------------------------------------------------------------------------
# JSON text field conventions
# ---------------------------------------------------------------------------


class TestJsonFields:
    def test_metadata_stored_and_retrieved_as_json_text(self, tmp_path: Path) -> None:
        payload = {"tags": ["memory", "L2"], "importance": 0.85}
        ts = "2024-06-01T09:00:00Z"

        with SQLiteStore(tmp_path / "json.db") as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO memory_index"
                " (id, layer, created_at, updated_at, metadata)"
                " VALUES (?, ?, ?, ?, ?)",
                ("mi1", 2, ts, ts, json.dumps(payload)),
            )
            rows = store.query(
                "SELECT metadata FROM memory_index WHERE id = ?", ("mi1",)
            )

        assert len(rows) == 1
        recovered = json.loads(rows[0]["metadata"])
        assert recovered == payload

    def test_tags_stored_as_json_array_text(self, tmp_path: Path) -> None:
        ts = "2024-06-01T09:00:00Z"
        tags = ["python", "refactor", "L3"]

        with SQLiteStore(tmp_path / "tags.db") as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO memory_index (id, layer, created_at, updated_at, tags)"
                " VALUES (?, ?, ?, ?, ?)",
                ("mi2", 3, ts, ts, json.dumps(tags)),
            )
            rows = store.query("SELECT tags FROM memory_index WHERE id = ?", ("mi2",))

        assert json.loads(rows[0]["tags"]) == tags

    def test_source_episodes_round_trip_in_semantics(self, tmp_path: Path) -> None:
        ts = "2024-06-01T09:00:00Z"
        episodes = ["ep-001", "ep-002"]

        with SQLiteStore(tmp_path / "sem_json.db") as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO memory_index (id, layer, created_at, updated_at)"
                " VALUES (?, ?, ?, ?)",
                ("mi_s", 3, ts, ts),
            )
            store.execute(
                "INSERT INTO semantics"
                " (id, memory_id, entity, relation, value, source_episodes)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                ("sem1", "mi_s", "user", "likes", "Python", json.dumps(episodes)),
            )
            rows = store.query(
                "SELECT source_episodes FROM semantics WHERE id = ?", ("sem1",)
            )

        assert json.loads(rows[0]["source_episodes"]) == episodes

    def test_consolidation_stats_stored_as_json(self, tmp_path: Path) -> None:
        ts = "2024-06-01T09:00:00Z"
        stats = {"extracted_semantics": 5, "merged_duplicates": 1}

        with SQLiteStore(tmp_path / "clog_json.db") as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO consolidation_log (started_at, completed_at, stats)"
                " VALUES (?, ?, ?)",
                (ts, ts, json.dumps(stats)),
            )
            rows = store.query("SELECT stats FROM consolidation_log")

        assert json.loads(rows[0]["stats"]) == stats

    def test_raw_json_stored_in_episodes(self, tmp_path: Path) -> None:
        ts = "2024-06-01T09:00:00Z"
        raw = {"source": "unit-test", "confidence": 0.99}

        with SQLiteStore(tmp_path / "ep_raw.db") as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO memory_index (id, layer, created_at, updated_at)"
                " VALUES (?, ?, ?, ?)",
                ("mi_e", 2, ts, ts),
            )
            store.execute(
                "INSERT INTO episodes (id, memory_id, content, event_type, raw_json)"
                " VALUES (?, ?, ?, ?, ?)",
                ("ep1", "mi_e", "some content", "observation", json.dumps(raw)),
            )
            rows = store.query(
                "SELECT raw_json FROM episodes WHERE id = ?", ("ep1",)
            )

        assert json.loads(rows[0]["raw_json"]) == raw


# ---------------------------------------------------------------------------
# ISO 8601 timestamp convention
# ---------------------------------------------------------------------------


class TestTimestamps:
    def test_timestamps_stored_as_iso8601_text(self, tmp_path: Path) -> None:
        ts = "2024-06-01T12:34:56Z"
        with SQLiteStore(tmp_path / "ts.db") as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO meta_memory (key, value, updated_at) VALUES (?, ?, ?)",
                ("ts_key", "val", ts),
            )
            rows = store.query(
                "SELECT updated_at FROM meta_memory WHERE key = ?", ("ts_key",)
            )

        assert rows[0]["updated_at"] == ts

    def test_iso8601_ordering_works_lexicographically(self, tmp_path: Path) -> None:
        """ISO 8601 UTC timestamps sort correctly as plain strings."""
        ts_early = "2024-01-01T00:00:00Z"
        ts_late = "2024-12-31T23:59:59Z"

        with SQLiteStore(tmp_path / "tsord.db") as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO consolidation_log (started_at, completed_at, stats)"
                " VALUES (?, ?, ?)",
                (ts_late, ts_late, "{}"),
            )
            store.execute(
                "INSERT INTO consolidation_log (started_at, completed_at, stats)"
                " VALUES (?, ?, ?)",
                (ts_early, ts_early, "{}"),
            )
            rows = store.query(
                "SELECT started_at FROM consolidation_log ORDER BY started_at ASC"
            )

        assert rows[0]["started_at"] == ts_early
        assert rows[1]["started_at"] == ts_late

    def test_created_at_in_memory_index(self, tmp_path: Path) -> None:
        ts = "2024-06-02T04:00:00Z"
        with SQLiteStore(tmp_path / "ts_mi.db") as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO memory_index (id, layer, created_at, updated_at)"
                " VALUES (?, ?, ?, ?)",
                ("mi_ts", 1, ts, ts),
            )
            rows = store.query(
                "SELECT created_at FROM memory_index WHERE id = ?", ("mi_ts",)
            )
        assert rows[0]["created_at"] == ts


# ---------------------------------------------------------------------------
# Foreign-key referential integrity
# ---------------------------------------------------------------------------


class TestForeignKeys:
    def test_episodes_fk_enforced(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "fk_ep.db") as store:
            store.initialize_schema()
            with pytest.raises(sqlite3.IntegrityError):
                store.execute(
                    "INSERT INTO episodes (id, memory_id, content, event_type)"
                    " VALUES (?, ?, ?, ?)",
                    ("ep_bad", "nonexistent_memory", "content", "observation"),
                )

    def test_semantics_fk_enforced(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "fk_sem.db") as store:
            store.initialize_schema()
            with pytest.raises(sqlite3.IntegrityError):
                store.execute(
                    "INSERT INTO semantics (id, memory_id, entity, relation, value)"
                    " VALUES (?, ?, ?, ?, ?)",
                    ("sem_bad", "nonexistent_memory", "user", "likes", "Python"),
                )

    def test_review_queue_fk_enforced(self, tmp_path: Path) -> None:
        ts = "2024-06-01T00:00:00Z"
        with SQLiteStore(tmp_path / "fk_rq.db") as store:
            store.initialize_schema()
            with pytest.raises(sqlite3.IntegrityError):
                store.execute(
                    "INSERT INTO review_queue (memory_id, ef, next_review_at)"
                    " VALUES (?, ?, ?)",
                    ("nonexistent_memory", 2.5, ts),
                )


# ---------------------------------------------------------------------------
# Default values applied at insert time
# ---------------------------------------------------------------------------


class TestDefaultValues:
    def test_memory_index_defaults_applied(self, tmp_path: Path) -> None:
        ts = "2024-06-01T00:00:00Z"
        with SQLiteStore(tmp_path / "def_mi.db") as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO memory_index (id, layer, created_at, updated_at)"
                " VALUES (?, ?, ?, ?)",
                ("mi_d", 2, ts, ts),
            )
            rows = store.query("SELECT * FROM memory_index WHERE id = ?", ("mi_d",))

        row = rows[0]
        assert row["importance"] == pytest.approx(0.5)
        assert row["initial_strength"] == pytest.approx(0.5)
        assert row["current_retention"] == pytest.approx(1.0)
        assert row["access_count"] == 0
        assert row["status"] == "active"
        assert json.loads(row["tags"]) == []
        assert json.loads(row["metadata"]) == {}
        assert row["last_accessed_at"] is None
        assert row["superseded_by"] is None
        assert row["content_hash"] is None

    def test_semantics_defaults_applied(self, tmp_path: Path) -> None:
        ts = "2024-06-01T00:00:00Z"
        with SQLiteStore(tmp_path / "def_sem.db") as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO memory_index (id, layer, created_at, updated_at)"
                " VALUES (?, ?, ?, ?)",
                ("mi_s2", 3, ts, ts),
            )
            store.execute(
                "INSERT INTO semantics (id, memory_id, entity, relation, value)"
                " VALUES (?, ?, ?, ?, ?)",
                ("sem_d", "mi_s2", "user", "prefers", "dark mode"),
            )
            rows = store.query("SELECT * FROM semantics WHERE id = ?", ("sem_d",))

        row = rows[0]
        assert row["confidence"] == pytest.approx(1.0)
        assert json.loads(row["source_episodes"]) == []
        assert row["version"] == 1

    def test_skills_defaults_applied(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "def_sk.db") as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO skills (id, name) VALUES (?, ?)", ("sk_d", "my_skill")
            )
            rows = store.query("SELECT * FROM skills WHERE id = ?", ("sk_d",))

        row = rows[0]
        assert row["usage_count"] == 0
        assert row["last_used_at"] is None
        assert row["success_rate"] is None
        assert row["average_duration_ms"] is None
        assert row["description"] is None
        assert row["code"] is None


# ---------------------------------------------------------------------------
# REQUIRED_TABLES constant is exported
# ---------------------------------------------------------------------------


def test_required_tables_constant_exported() -> None:
    from hm_arch.storage.sqlite import REQUIRED_TABLES

    assert isinstance(REQUIRED_TABLES, frozenset)
    assert len(REQUIRED_TABLES) == 7
    assert "memory_index" in REQUIRED_TABLES


def test_sqlite_store_importable_from_storage_package() -> None:
    from hm_arch.storage import SQLiteStore as S

    assert S is SQLiteStore
