"""Backward-compatible SQLite schema migrations for HM-Arch."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .sqlite import SQLiteStore

CURRENT_SCHEMA_VERSION = 2

_MIGRATION_V2_COLUMNS: tuple[str, ...] = (
    "provenance_agent",
    "provenance_project",
    "provenance_session",
    "memory_type",
)


def apply_migrations(store: SQLiteStore) -> None:
    """Upgrade an opened database to :data:`CURRENT_SCHEMA_VERSION`."""
    _ensure_schema_version_table(store)
    version = _read_version(store)
    if version is None:
        version = _detect_version(store)

    if version < 2:
        _migrate_to_v2(store)
        version = 2

    _write_version(store, version)


def _ensure_schema_version_table(store: SQLiteStore) -> None:
    store.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL
        )
        """
    )


def _read_version(store: SQLiteStore) -> int | None:
    rows = store.query("SELECT version FROM schema_version LIMIT 1")
    if not rows:
        return None
    return int(rows[0]["version"])


def _write_version(store: SQLiteStore, version: int) -> None:
    rows = store.query("SELECT version FROM schema_version LIMIT 1")
    if rows:
        store.execute("UPDATE schema_version SET version = ?", (version,))
    else:
        store.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))


def _detect_version(store: SQLiteStore) -> int:
    """Infer schema version for databases created before ``schema_version``."""
    cols = _column_names(store, "memory_index")
    if all(column in cols for column in _MIGRATION_V2_COLUMNS):
        return 2
    return 1


def _migrate_to_v2(store: SQLiteStore) -> None:
    cols = _column_names(store, "memory_index")
    for column in _MIGRATION_V2_COLUMNS:
        if column not in cols:
            store.execute(f"ALTER TABLE memory_index ADD COLUMN {column} TEXT")

    store.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memory_provenance_agent
        ON memory_index(provenance_agent)
        """
    )
    store.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memory_provenance_project
        ON memory_index(provenance_project)
        """
    )
    store.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memory_provenance_session
        ON memory_index(provenance_session)
        """
    )
    store.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memory_memory_type
        ON memory_index(memory_type)
        """
    )


def _column_names(store: SQLiteStore, table: str) -> set[str]:
    rows = store.query(f"PRAGMA table_info({table})")
    return {row["name"] for row in rows}
