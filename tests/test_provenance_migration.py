"""Tests for memory provenance schema, migration, and search surfacing (MEM-53)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hm_arch import EventType, HMArch, MemoryProvenance
from hm_arch.storage.migrations import CURRENT_SCHEMA_VERSION, apply_migrations
from hm_arch.storage.sqlite import SQLiteStore

_LEGACY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memory_index (
    id               TEXT    PRIMARY KEY,
    layer            INTEGER NOT NULL,
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL,
    importance       REAL    NOT NULL DEFAULT 0.5,
    initial_strength REAL    NOT NULL DEFAULT 0.5,
    current_retention REAL   NOT NULL DEFAULT 1.0,
    last_accessed_at TEXT,
    access_count     INTEGER NOT NULL DEFAULT 0,
    status           TEXT    NOT NULL DEFAULT 'active',
    superseded_by    TEXT,
    tags             TEXT    NOT NULL DEFAULT '[]',
    metadata         TEXT    NOT NULL DEFAULT '{}',
    content_hash     TEXT
);

CREATE TABLE IF NOT EXISTS episodes (
    id             TEXT    PRIMARY KEY,
    memory_id      TEXT    NOT NULL REFERENCES memory_index(id),
    content        TEXT    NOT NULL,
    event_type     TEXT    NOT NULL,
    emotion_score  REAL,
    context_window TEXT,
    raw_json       TEXT
);
"""


def _col_names(store: SQLiteStore, table: str) -> set[str]:
    rows = store.query(f"PRAGMA table_info({table})")
    return {row["name"] for row in rows}


def _seed_legacy_memory(db_path: Path) -> tuple[str, str]:
    conn = sqlite3.connect(db_path)
    conn.executescript(_LEGACY_SCHEMA_SQL)
    memory_id = "legacy-memory-001"
    episode_id = "legacy-episode-001"
    created_at = "2024-01-01T00:00:00+00:00"
    conn.execute(
        """
        INSERT INTO memory_index (
            id, layer, created_at, updated_at, importance,
            initial_strength, current_retention, status, tags, metadata
        ) VALUES (?, 2, ?, ?, 0.8, 1.0, 1.0, 'active', '[]', '{}')
        """,
        (memory_id, created_at, created_at),
    )
    conn.execute(
        """
        INSERT INTO episodes (
            id, memory_id, content, event_type
        ) VALUES (?, ?, ?, ?)
        """,
        (episode_id, memory_id, "legacy content should survive migration", "observation"),
    )
    conn.commit()
    conn.close()
    return memory_id, "legacy content should survive migration"


class TestProvenanceMigration:
    def test_legacy_database_migrates_without_data_loss(self, tmp_path: Path) -> None:
        db_path = tmp_path / "legacy.db"
        memory_id, content = _seed_legacy_memory(db_path)

        with SQLiteStore(db_path) as store:
            store.initialize_schema()
            cols = _col_names(store, "memory_index")
            version_rows = store.query("SELECT version FROM schema_version")

        assert int(version_rows[0]["version"]) == CURRENT_SCHEMA_VERSION
        for column in (
            "provenance_agent",
            "provenance_project",
            "provenance_session",
            "memory_type",
        ):
            assert column in cols

        with SQLiteStore(db_path) as store:
            rows = store.query(
                """
                SELECT e.content, mi.provenance_agent, mi.memory_type
                FROM memory_index mi
                JOIN episodes e ON e.memory_id = mi.id
                WHERE mi.id = ?
                """,
                (memory_id,),
            )

        assert rows[0]["content"] == content
        assert rows[0]["provenance_agent"] is None
        assert rows[0]["memory_type"] is None

    def test_fresh_database_records_schema_version(self, tmp_path: Path) -> None:
        with SQLiteStore(tmp_path / "fresh.db") as store:
            store.initialize_schema()
            version_rows = store.query("SELECT version FROM schema_version")
        assert int(version_rows[0]["version"]) == CURRENT_SCHEMA_VERSION


class TestProvenanceRoundTrip:
    def test_add_preserves_provenance_columns_and_metadata(self, tmp_path: Path) -> None:
        db_path = tmp_path / "roundtrip.db"
        memory = HMArch(db_path=str(db_path))
        receipt = memory.add(
            "User prefers Rust for systems work",
            event_type=EventType.DECISION,
            agent="codex",
            project="/workspace/demo",
            session="session-abc-123",
        )
        memory.close()

        with SQLiteStore(db_path) as store:
            rows = store.query(
                """
                SELECT provenance_agent,
                       provenance_project,
                       provenance_session,
                       memory_type,
                       metadata
                FROM memory_index
                WHERE id = ?
                """,
                (receipt.memory_id,),
            )

        row = rows[0]
        assert row["provenance_agent"] == "codex"
        assert row["provenance_project"] == "/workspace/demo"
        assert row["provenance_session"] == "session-abc-123"
        assert row["memory_type"] == "decision"

    def test_search_exposes_provenance_for_consumers(self, tmp_path: Path) -> None:
        memory = HMArch(db_path=str(tmp_path / "search.db"))
        memory.add(
            "Project uses PostgreSQL for persistence",
            event_type=EventType.OBSERVATION,
            agent="claude-code",
            project="/repos/app",
            session="sess-42",
        )
        result = memory.search("PostgreSQL persistence", min_retention=0.0)
        memory.close()

        assert result.results
        hit = next(
            item
            for item in result.results
            if "PostgreSQL" in item.content
        )
        assert isinstance(hit.provenance, MemoryProvenance)
        assert hit.provenance.agent == "claude-code"
        assert hit.provenance.project == "/repos/app"
        assert hit.provenance.session == "sess-42"
        assert hit.provenance.memory_type == "observation"
        assert hit.provenance.created_at.tzinfo is not None

    def test_reopen_database_preserves_provenance_in_search(self, tmp_path: Path) -> None:
        db_path = tmp_path / "reopen.db"
        with HMArch(db_path=str(db_path)) as memory:
            memory.add(
                "Always run tests before pushing",
                agent="cursor",
                project="/workspace/hm-arch",
                session="sess-reopen",
            )

        with HMArch(db_path=str(db_path)) as memory:
            result = memory.search("run tests", min_retention=0.0)

        hit = result.results[0]
        assert hit.provenance is not None
        assert hit.provenance.agent == "cursor"
        assert hit.provenance.project == "/workspace/hm-arch"
        assert hit.provenance.session == "sess-reopen"

    def test_receipt_includes_provenance(self, tmp_path: Path) -> None:
        with HMArch(db_path=":memory:") as memory:
            receipt = memory.add(
                "Receipt provenance probe",
                agent="codex",
                project="/tmp/project",
                session="sess-receipt",
            )
        assert receipt.provenance is not None
        assert receipt.provenance.agent == "codex"
        assert receipt.provenance.project == "/tmp/project"
        assert receipt.provenance.session == "sess-receipt"
        assert receipt.provenance.memory_type == "conversation"

    def test_apply_migrations_is_idempotent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "idempotent.db"
        _seed_legacy_memory(db_path)
        with SQLiteStore(db_path) as store:
            store.initialize_schema()
            apply_migrations(store)
            apply_migrations(store)
            version_rows = store.query("SELECT version FROM schema_version")
        assert int(version_rows[0]["version"]) == CURRENT_SCHEMA_VERSION
