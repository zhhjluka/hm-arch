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
        # connection should be closed even after exception
        assert store.is_connected is False

    def test_in_memory_store(self) -> None:
        with SQLiteStore(":memory:") as store:
            store.initialize_schema()
            tables = _table_names(store)
            assert REQUIRED_TABLES.issubset(tables)


# ---------------------------------------------------------------------------
# Schema initialization
# ---------------------------------------------------------------------------


class TestInitializeSchema:
    def test_all_required_tables_created(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "schema.db") as store:
            store.initialize_schema()
            tables = _table_names(store)
        assert REQUIRED_TABLES.issubset(tables), (
            f"Missing tables: {REQUIRED_TABLES - tables}"
        )

    def test_initialize_schema_is_idempotent(self, tmp_path: Path) -> None:
        db = tmp_path / "idempotent.db"
        with SQLiteStore(db) as store:
            store.initialize_schema()
            store.initialize_schema()  # calling twice must not raise
            tables = _table_names(store)
        assert REQUIRED_TABLES.issubset(tables)

    def test_memory_index_columns(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "cols.db") as store:
            store.initialize_schema()
            cols = {
                row["name"]
                for row in store.query("PRAGMA table_info(memory_index)")
            }
        expected = {
            "memory_id", "layer", "event_type", "content",
            "importance", "initial_strength", "retention",
            "status", "created_at", "updated_at", "meta_json",
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_episodes_columns(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "ep.db") as store:
            store.initialize_schema()
            cols = {
                row["name"]
                for row in store.query("PRAGMA table_info(episodes)")
            }
        expected = {
            "episode_id", "memory_id", "event_type", "content",
            "importance", "retention", "ease_factor", "review_count",
            "next_review_at", "created_at", "updated_at", "extra_json",
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_semantics_columns(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "sem.db") as store:
            store.initialize_schema()
            cols = {
                row["name"]
                for row in store.query("PRAGMA table_info(semantics)")
            }
        expected = {
            "semantic_id", "memory_id", "entity", "relation", "value",
            "confidence", "retention", "status", "source_episode_id",
            "created_at", "updated_at", "extra_json",
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_review_queue_columns(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "rq.db") as store:
            store.initialize_schema()
            cols = {
                row["name"]
                for row in store.query("PRAGMA table_info(review_queue)")
            }
        expected = {
            "review_id", "memory_id", "scheduled_at", "priority",
            "review_type", "created_at", "extra_json",
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_consolidation_log_columns(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "clog.db") as store:
            store.initialize_schema()
            cols = {
                row["name"]
                for row in store.query("PRAGMA table_info(consolidation_log)")
            }
        expected = {
            "log_id", "started_at", "finished_at",
            "extracted_semantics", "merged_duplicates", "resolved_conflicts",
            "archived_to_l4", "scheduled_reviews", "marked_deletable",
            "duration_seconds", "extra_json",
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"


# ---------------------------------------------------------------------------
# execute() and query() helpers
# ---------------------------------------------------------------------------


class TestExecuteAndQuery:
    def test_execute_insert_and_query_select(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "rw.db") as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO meta_memory (meta_id, key, value_json, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                ("m1", "agent_name", '"TestBot"', "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"),
            )
            rows = store.query("SELECT * FROM meta_memory WHERE key = ?", ("agent_name",))

        assert len(rows) == 1
        assert rows[0]["key"] == "agent_name"
        assert json.loads(rows[0]["value_json"]) == "TestBot"

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
                "INSERT INTO skills (skill_id, name, content, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                ("sk1", "ping", "return pong", "2024-06-01T12:00:00Z", "2024-06-01T12:00:00Z"),
            )
            rows = store.query("SELECT * FROM skills WHERE skill_id = ?", ("sk1",))

        assert rows[0]["name"] == "ping"
        assert rows[0]["content"] == "return pong"

    def test_execute_returns_cursor_with_lastrowid(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "cursor.db") as store:
            store.initialize_schema()
            cursor = store.execute(
                "INSERT INTO skills (skill_id, name, content, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                ("sk2", "check", "ok", "2024-06-01T00:00:00Z", "2024-06-01T00:00:00Z"),
            )
        assert cursor.lastrowid is not None

    def test_named_params_work(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "named.db") as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO meta_memory (meta_id, key, value_json, created_at, updated_at)"
                " VALUES (:mid, :key, :val, :ca, :ua)",
                {
                    "mid": "n1",
                    "key": "lang",
                    "val": '"Python"',
                    "ca": "2024-01-01T00:00:00Z",
                    "ua": "2024-01-01T00:00:00Z",
                },
            )
            rows = store.query("SELECT value_json FROM meta_memory WHERE key = :key", {"key": "lang"})

        assert rows[0]["value_json"] == '"Python"'

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

        # First connection: create schema and write a row.
        with SQLiteStore(db) as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO meta_memory (meta_id, key, value_json, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                ("p1", "session", '"active"', "2024-06-01T00:00:00Z", "2024-06-01T00:00:00Z"),
            )

        # Second connection: verify the row is still there.
        with SQLiteStore(db) as store:
            rows = store.query("SELECT value_json FROM meta_memory WHERE key = ?", ("session",))

        assert len(rows) == 1
        assert json.loads(rows[0]["value_json"]) == "active"

    def test_schema_preserved_after_reopen(self, tmp_path: Path) -> None:
        db = tmp_path / "schema_persist.db"

        with SQLiteStore(db) as store:
            store.initialize_schema()

        with SQLiteStore(db) as store:
            tables = _table_names(store)

        assert REQUIRED_TABLES.issubset(tables)

    def test_multiple_rows_persist(self, tmp_path: Path) -> None:
        db = tmp_path / "multi.db"

        ts = "2024-06-01T00:00:00Z"
        with SQLiteStore(db) as store:
            store.initialize_schema()
            for i in range(5):
                store.execute(
                    "INSERT INTO skills (skill_id, name, content, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (f"sk{i}", f"skill_{i}", f"body_{i}", ts, ts),
                )

        with SQLiteStore(db) as store:
            rows = store.query("SELECT skill_id FROM skills ORDER BY skill_id")

        assert len(rows) == 5
        assert [r["skill_id"] for r in rows] == ["sk0", "sk1", "sk2", "sk3", "sk4"]


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
        with SQLiteStore(db) as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO meta_memory (meta_id, key, value_json, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                ("iso_id", "marker", f'"{value}"', "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"),
            )

    def _read_marker(self, db: Path) -> str:
        with SQLiteStore(db) as store:
            rows = store.query("SELECT value_json FROM meta_memory WHERE key = 'marker'")
        return json.loads(rows[0]["value_json"])

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
    def test_meta_json_stored_and_retrieved_as_text(self, tmp_path: Path) -> None:
        payload = {"tags": ["memory", "L2"], "importance": 0.85}
        ts = "2024-06-01T09:00:00Z"

        with SQLiteStore(tmp_path / "json.db") as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO memory_index"
                " (memory_id, layer, content, created_at, updated_at, meta_json)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                ("mi1", 2, "test content", ts, ts, json.dumps(payload)),
            )
            rows = store.query("SELECT meta_json FROM memory_index WHERE memory_id = ?", ("mi1",))

        assert len(rows) == 1
        recovered = json.loads(rows[0]["meta_json"])
        assert recovered == payload

    def test_extra_json_round_trip_in_episodes(self, tmp_path: Path) -> None:
        ts = "2024-06-01T09:00:00Z"
        extra = {"source": "unit-test", "confidence": 0.99}

        with SQLiteStore(tmp_path / "ep_json.db") as store:
            store.initialize_schema()
            # episodes has a FK on memory_index; insert parent first.
            store.execute(
                "INSERT INTO memory_index (memory_id, layer, content, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                ("mi_ep", 2, "ep content", ts, ts),
            )
            store.execute(
                "INSERT INTO episodes"
                " (episode_id, memory_id, content, created_at, updated_at, extra_json)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                ("ep1", "mi_ep", "ep content", ts, ts, json.dumps(extra)),
            )
            rows = store.query(
                "SELECT extra_json FROM episodes WHERE episode_id = ?", ("ep1",)
            )

        assert json.loads(rows[0]["extra_json"]) == extra


# ---------------------------------------------------------------------------
# ISO 8601 timestamp convention
# ---------------------------------------------------------------------------


class TestTimestamps:
    def test_timestamps_stored_as_iso8601_text(self, tmp_path: Path) -> None:
        ts = "2024-06-01T12:34:56Z"
        with SQLiteStore(tmp_path / "ts.db") as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO meta_memory (meta_id, key, value_json, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                ("ts1", "ts_key", '"val"', ts, ts),
            )
            rows = store.query("SELECT created_at FROM meta_memory WHERE meta_id = ?", ("ts1",))

        assert rows[0]["created_at"] == ts

    def test_iso8601_ordering_works_lexicographically(self, tmp_path: Path) -> None:
        """ISO 8601 timestamps in UTC sort correctly as plain strings."""
        ts_early = "2024-01-01T00:00:00Z"
        ts_late = "2024-12-31T23:59:59Z"

        with SQLiteStore(tmp_path / "tsord.db") as store:
            store.initialize_schema()
            store.execute(
                "INSERT INTO consolidation_log (log_id, started_at) VALUES (?, ?)",
                ("log_late", ts_late),
            )
            store.execute(
                "INSERT INTO consolidation_log (log_id, started_at) VALUES (?, ?)",
                ("log_early", ts_early),
            )
            rows = store.query(
                "SELECT log_id FROM consolidation_log ORDER BY started_at ASC"
            )

        assert rows[0]["log_id"] == "log_early"
        assert rows[1]["log_id"] == "log_late"


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
