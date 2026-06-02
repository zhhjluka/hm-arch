"""SQLite storage backend for HM-Arch.

Provides a thin, stdlib-only wrapper around :mod:`sqlite3` that:

* opens (or creates) a SQLite database file,
* initializes all PRD-required tables with ISO 8601 timestamps and JSON text
  fields,
* exposes ``execute`` / ``query`` helpers for callers that need raw SQL,
* supports both explicit ``connect`` / ``close`` and Python context-manager
  usage.

No external dependencies are required beyond the Python standard library.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Mapping, Sequence, Union

# Type alias accepted by both execute() and query()
_Params = Union[Sequence, Mapping]

# ---------------------------------------------------------------------------
# DDL — one CREATE TABLE IF NOT EXISTS per PRD-required table
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
-- Central index: one row per persisted memory, regardless of layer.
CREATE TABLE IF NOT EXISTS memory_index (
    memory_id   TEXT    PRIMARY KEY,
    layer       INTEGER NOT NULL,
    event_type  TEXT,
    content     TEXT    NOT NULL,
    importance  REAL    NOT NULL DEFAULT 0.0,
    initial_strength REAL NOT NULL DEFAULT 1.0,
    retention   REAL    NOT NULL DEFAULT 1.0,
    status      TEXT    NOT NULL DEFAULT 'active',
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL,
    meta_json   TEXT    NOT NULL DEFAULT '{}'
);

-- L2 episodic buffer: one row per episode, linked to memory_index.
CREATE TABLE IF NOT EXISTS episodes (
    episode_id      TEXT    PRIMARY KEY,
    memory_id       TEXT    NOT NULL REFERENCES memory_index(memory_id),
    event_type      TEXT,
    content         TEXT    NOT NULL,
    importance      REAL    NOT NULL DEFAULT 0.0,
    retention       REAL    NOT NULL DEFAULT 1.0,
    ease_factor     REAL    NOT NULL DEFAULT 2.5,
    review_count    INTEGER NOT NULL DEFAULT 0,
    next_review_at  TEXT,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    extra_json      TEXT    NOT NULL DEFAULT '{}'
);

-- L3 semantic memory: subject–relation–object triples.
CREATE TABLE IF NOT EXISTS semantics (
    semantic_id         TEXT    PRIMARY KEY,
    memory_id           TEXT    NOT NULL REFERENCES memory_index(memory_id),
    entity              TEXT    NOT NULL,
    relation            TEXT    NOT NULL,
    value               TEXT    NOT NULL,
    confidence          REAL    NOT NULL DEFAULT 1.0,
    retention           REAL    NOT NULL DEFAULT 1.0,
    status              TEXT    NOT NULL DEFAULT 'active',
    source_episode_id   TEXT,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL,
    extra_json          TEXT    NOT NULL DEFAULT '{}'
);

-- L5 procedural memory / skills.
CREATE TABLE IF NOT EXISTS skills (
    skill_id        TEXT    PRIMARY KEY,
    name            TEXT    NOT NULL,
    description     TEXT,
    content         TEXT    NOT NULL,
    trigger_pattern TEXT,
    usage_count     INTEGER NOT NULL DEFAULT 0,
    last_used_at    TEXT,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    extra_json      TEXT    NOT NULL DEFAULT '{}'
);

-- L6 meta-cognitive store: arbitrary key/value pairs serialised as JSON.
CREATE TABLE IF NOT EXISTS meta_memory (
    meta_id     TEXT    PRIMARY KEY,
    key         TEXT    NOT NULL UNIQUE,
    value_json  TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);

-- ASM-2 review scheduling queue.
CREATE TABLE IF NOT EXISTS review_queue (
    review_id    TEXT    PRIMARY KEY,
    memory_id    TEXT    NOT NULL REFERENCES memory_index(memory_id),
    scheduled_at TEXT    NOT NULL,
    priority     REAL    NOT NULL DEFAULT 0.5,
    review_type  TEXT    NOT NULL DEFAULT 'retention',
    created_at   TEXT    NOT NULL,
    extra_json   TEXT    NOT NULL DEFAULT '{}'
);

-- Audit log of consolidation cycle runs.
CREATE TABLE IF NOT EXISTS consolidation_log (
    log_id               TEXT    PRIMARY KEY,
    started_at           TEXT    NOT NULL,
    finished_at          TEXT,
    extracted_semantics  INTEGER NOT NULL DEFAULT 0,
    merged_duplicates    INTEGER NOT NULL DEFAULT 0,
    resolved_conflicts   INTEGER NOT NULL DEFAULT 0,
    archived_to_l4       INTEGER NOT NULL DEFAULT 0,
    scheduled_reviews    INTEGER NOT NULL DEFAULT 0,
    marked_deletable     INTEGER NOT NULL DEFAULT 0,
    duration_seconds     REAL,
    extra_json           TEXT    NOT NULL DEFAULT '{}'
);
"""

# Tables that must exist after initialize_schema() is called.
REQUIRED_TABLES: frozenset[str] = frozenset(
    {
        "memory_index",
        "episodes",
        "semantics",
        "skills",
        "meta_memory",
        "review_queue",
        "consolidation_log",
    }
)


class SQLiteStore:
    """Thin wrapper around :mod:`sqlite3` for the HM-Arch storage layer.

    Parameters
    ----------
    path:
        Filesystem path to the SQLite database file.  Pass ``":memory:"`` for
        a purely in-process database (useful in tests).

    Examples
    --------
    **Explicit open / close**::

        store = SQLiteStore("agent.db")
        store.connect()
        store.initialize_schema()
        store.execute("INSERT INTO meta_memory VALUES (?,?,?,?,?)",
                      ("id1","key","value","2024-01-01T00:00:00Z","2024-01-01T00:00:00Z"))
        rows = store.query("SELECT * FROM meta_memory")
        store.close()

    **Context manager** (preferred)::

        with SQLiteStore("agent.db") as store:
            store.initialize_schema()
            rows = store.query("SELECT name FROM sqlite_master WHERE type='table'")
    """

    def __init__(self, path: Union[str, Path]) -> None:
        self._path = str(path)
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> "SQLiteStore":
        """Open the database connection.

        Enables WAL journal mode and :data:`sqlite3.Row` row factory so
        callers can access columns by name.

        Returns *self* so callers can chain ``store.connect().initialize_schema()``.
        """
        if self._conn is not None:
            return self
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        # WAL mode is safe for concurrent readers and single writer.
        self._conn.execute("PRAGMA journal_mode=WAL;")
        # Enforce FK constraints so referential integrity is checked at write time.
        self._conn.execute("PRAGMA foreign_keys=ON;")
        return self

    def close(self) -> None:
        """Commit any pending transaction and close the connection."""
        if self._conn is not None:
            self._conn.commit()
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Context-manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "SQLiteStore":
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is None:
            self.close()
        else:
            # Roll back on error, then close without committing.
            if self._conn is not None:
                self._conn.rollback()
                self._conn.close()
                self._conn = None

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def initialize_schema(self) -> None:
        """Create all PRD-required tables (idempotent).

        Safe to call on an existing database: ``CREATE TABLE IF NOT EXISTS``
        means tables that already exist are left untouched.

        Raises
        ------
        RuntimeError
            If the store has not been connected yet.
        """
        self._require_connection()
        self._conn.executescript(_SCHEMA_SQL)  # type: ignore[union-attr]
        self._conn.commit()  # type: ignore[union-attr]

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def execute(self, sql: str, params: _Params = ()) -> sqlite3.Cursor:
        """Execute a single SQL statement and return the cursor.

        Parameters
        ----------
        sql:
            A single SQL statement.  Use ``?`` placeholders for positional
            parameters, or ``:name`` / ``@name`` for named parameters.
        params:
            Positional sequence or named mapping of parameter values.

        Returns
        -------
        sqlite3.Cursor
            The cursor after execution.  Callers can read ``cursor.lastrowid``
            or ``cursor.rowcount`` if needed.
        """
        self._require_connection()
        cursor = self._conn.execute(sql, params)  # type: ignore[union-attr]
        self._conn.commit()  # type: ignore[union-attr]
        return cursor

    def query(self, sql: str, params: _Params = ()) -> list[sqlite3.Row]:
        """Execute a SELECT statement and return all matching rows.

        Parameters
        ----------
        sql:
            A SELECT (or any statement that returns rows).
        params:
            Positional sequence or named mapping of parameter values.

        Returns
        -------
        list[sqlite3.Row]
            All rows returned by the query.  Each row can be accessed by
            column name (e.g. ``row["memory_id"]``) or by index.
        """
        self._require_connection()
        cursor = self._conn.execute(sql, params)  # type: ignore[union-attr]
        return cursor.fetchall()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_connection(self) -> None:
        if self._conn is None:
            raise RuntimeError(
                "SQLiteStore is not connected.  "
                "Call connect() or use the store as a context manager first."
            )

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def path(self) -> str:
        """Filesystem path (or ``:memory:``) of the underlying database."""
        return self._path

    @property
    def is_connected(self) -> bool:
        """``True`` if a live connection exists."""
        return self._conn is not None
