"""Concurrent SQLite access tests for multi-agent usage (MEM-57).

These tests are offline and deterministic: they use threading and
multiprocessing against temporary file-backed databases with short lock holds.
"""

from __future__ import annotations

import multiprocessing as mp
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from hm_arch.storage.sqlite import (
    DEFAULT_BUSY_TIMEOUT_MS,
    DEFAULT_LOCK_RETRIES,
    SQLiteStore,
)

_TS = "2024-06-01T00:00:00Z"


def _init_meta_table(db: Path) -> None:
    with SQLiteStore(db) as store:
        store.initialize_schema()


def _insert_meta(db: Path, key: str, value: str) -> None:
    with SQLiteStore(db) as store:
        store.execute(
            "INSERT INTO meta_memory (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, _TS),
        )


def _hold_write_lock(db: Path, hold_seconds: float, ready: mp.Event, done: mp.Event) -> None:
    store = SQLiteStore(db)
    store.connect()
    conn = store._conn
    assert conn is not None
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        "INSERT INTO meta_memory (key, value, updated_at) VALUES (?, ?, ?)",
        ("lock_holder", "holding", _TS),
    )
    ready.set()
    time.sleep(hold_seconds)
    conn.commit()
    store.close()
    done.set()


def _write_with_retries(db: Path, key: str, result: mp.Queue) -> None:
    try:
        with SQLiteStore(
            db,
            busy_timeout_ms=5_000,
            lock_retries=8,
            lock_retry_base_delay_s=0.02,
        ) as store:
            store.execute(
                "INSERT INTO meta_memory (key, value, updated_at) VALUES (?, ?, ?)",
                (key, "ok", _TS),
            )
        result.put("ok")
    except Exception as exc:  # pragma: no cover - surfaced via queue
        result.put(str(exc))


class TestConcurrencyPragmas:
    def test_wal_mode_on_file_database(self, tmp_path: Path) -> None:
        db = tmp_path / "wal.db"
        with SQLiteStore(db) as store:
            row = store.query("PRAGMA journal_mode")
        assert row[0]["journal_mode"].lower() == "wal"
        assert (tmp_path / "wal.db-wal").exists() or db.exists()

    def test_busy_timeout_matches_config(self, tmp_path: Path) -> None:
        db = tmp_path / "busy.db"
        custom_ms = 12_345
        with SQLiteStore(db, busy_timeout_ms=custom_ms) as store:
            row = store.query("PRAGMA busy_timeout")
        assert int(row[0][0]) == custom_ms

    def test_defaults_match_module_constants(self) -> None:
        with SQLiteStore(":memory:") as store:
            row = store.query("PRAGMA busy_timeout")
        assert int(row[0][0]) == DEFAULT_BUSY_TIMEOUT_MS
        assert DEFAULT_LOCK_RETRIES >= 1


class TestLockErrorDetection:
    @pytest.mark.parametrize(
        "message",
        [
            "database is locked",
            "Database is locked",
            "database table is locked",
        ],
    )
    def test_detects_lock_errors(self, message: str) -> None:
        assert SQLiteStore._is_database_locked_error(sqlite3.OperationalError(message))

    def test_ignores_other_operational_errors(self) -> None:
        assert not SQLiteStore._is_database_locked_error(
            sqlite3.OperationalError("no such table: missing")
        )


class TestThreadedContention:
    def test_write_retries_while_another_connection_holds_lock(
        self, tmp_path: Path
    ) -> None:
        db = tmp_path / "thread_contention.db"
        _init_meta_table(db)

        lock_acquired = threading.Event()
        release_lock = threading.Event()
        writer_error: list[BaseException] = []

        def hold_lock() -> None:
            store = SQLiteStore(db)
            store.connect()
            conn = store._conn
            assert conn is not None
            try:
                conn.execute("BEGIN IMMEDIATE")
                lock_acquired.set()
                release_lock.wait(timeout=5)
                conn.commit()
            except BaseException as exc:
                writer_error.append(exc)
            finally:
                store.close()

        holder = threading.Thread(target=hold_lock)
        holder.start()
        assert lock_acquired.wait(timeout=5)

        def competing_write() -> None:
            with SQLiteStore(
                db,
                busy_timeout_ms=5_000,
                lock_retries=10,
                lock_retry_base_delay_s=0.02,
            ) as store:
                store.execute(
                    "INSERT INTO meta_memory (key, value, updated_at) VALUES (?, ?, ?)",
                    ("competitor", "success", _TS),
                )

        writer = threading.Thread(target=competing_write)
        writer.start()
        time.sleep(0.05)
        release_lock.set()
        writer.join(timeout=10)
        holder.join(timeout=10)

        assert not writer_error
        with SQLiteStore(db) as store:
            rows = store.query(
                "SELECT key FROM meta_memory WHERE key = ?", ("competitor",)
            )
        assert len(rows) == 1

    def test_concurrent_reads_during_write(self, tmp_path: Path) -> None:
        db = tmp_path / "read_during_write.db"
        _init_meta_table(db)
        _insert_meta(db, "seed", "value")

        write_started = threading.Event()
        stop_reads = threading.Event()
        read_errors: list[str] = []

        def reader() -> None:
            while not stop_reads.is_set():
                try:
                    with SQLiteStore(db) as store:
                        rows = store.query(
                            "SELECT value FROM meta_memory WHERE key = ?", ("seed",)
                        )
                    if rows and rows[0]["value"] != "value":
                        read_errors.append("unexpected value")
                except Exception as exc:  # pragma: no cover
                    read_errors.append(str(exc))
                time.sleep(0.01)

        def writer() -> None:
            write_started.set()
            with SQLiteStore(db) as store:
                for i in range(20):
                    store.execute(
                        "INSERT INTO meta_memory (key, value, updated_at) VALUES (?, ?, ?)",
                        (f"k{i}", "v", _TS),
                    )

        readers = [threading.Thread(target=reader) for _ in range(3)]
        for thread in readers:
            thread.start()

        writer_thread = threading.Thread(target=writer)
        writer_thread.start()
        write_started.wait(timeout=5)
        writer_thread.join(timeout=10)
        stop_reads.set()
        for thread in readers:
            thread.join(timeout=5)

        assert read_errors == []


class TestMultiprocessContention:
    def test_multiprocess_write_succeeds_after_lock_release(
        self, tmp_path: Path
    ) -> None:
        db = tmp_path / "mp_contention.db"
        _init_meta_table(db)

        ctx = mp.get_context("spawn")
        ready = ctx.Event()
        done = ctx.Event()
        result: mp.Queue[str] = ctx.Queue()

        holder = ctx.Process(
            target=_hold_write_lock,
            args=(db, 0.25, ready, done),
        )
        writer = ctx.Process(
            target=_write_with_retries,
            args=(db, "mp_writer", result),
        )

        holder.start()
        assert ready.wait(timeout=5)
        writer.start()

        writer.join(timeout=15)
        holder.join(timeout=15)
        assert done.wait(timeout=5)

        assert result.get(timeout=1) == "ok"
        with SQLiteStore(db) as store:
            rows = store.query(
                "SELECT key FROM meta_memory WHERE key = ?", ("mp_writer",)
            )
        assert len(rows) == 1

    def test_parallel_multiprocess_inserts(self, tmp_path: Path) -> None:
        db = tmp_path / "mp_parallel.db"
        _init_meta_table(db)

        ctx = mp.get_context("spawn")
        with ctx.Pool(processes=4) as pool:
            pool.starmap(_insert_meta, [(db, f"p{i}", f"v{i}") for i in range(12)])

        with SQLiteStore(db) as store:
            count = store.query("SELECT COUNT(*) AS n FROM meta_memory")[0]["n"]
        assert count == 12


class TestTransactionAndRetryLimits:
    def test_transaction_survives_begin_immediate_contention(
        self, tmp_path: Path
    ) -> None:
        db = tmp_path / "txn.db"
        _init_meta_table(db)

        lock_acquired = threading.Event()
        release_lock = threading.Event()

        def hold_lock() -> None:
            store = SQLiteStore(db)
            store.connect()
            conn = store._conn
            assert conn is not None
            conn.execute("BEGIN IMMEDIATE")
            lock_acquired.set()
            release_lock.wait(timeout=5)
            conn.commit()
            store.close()

        holder = threading.Thread(target=hold_lock)
        holder.start()
        assert lock_acquired.wait(timeout=5)

        with SQLiteStore(
            db,
            busy_timeout_ms=5_000,
            lock_retries=10,
            lock_retry_base_delay_s=0.02,
        ) as store:
            time.sleep(0.05)
            release_lock.set()
            holder.join(timeout=10)
            with store.transaction():
                store.execute_no_commit(
                    "INSERT INTO meta_memory (key, value, updated_at) VALUES (?, ?, ?)",
                    ("txn", "committed", _TS),
                )

        with SQLiteStore(db) as store:
            rows = store.query(
                "SELECT value FROM meta_memory WHERE key = ?", ("txn",)
            )
        assert rows[0]["value"] == "committed"

    def test_lock_retries_exhausted_raises(self, tmp_path: Path) -> None:
        db = tmp_path / "exhaust.db"
        _init_meta_table(db)

        store = SQLiteStore(db, busy_timeout_ms=1, lock_retries=0)
        store.connect()
        conn = store._conn
        assert conn is not None
        conn.execute("BEGIN IMMEDIATE")
        try:
            other = SQLiteStore(db, busy_timeout_ms=1, lock_retries=0)
            other.connect()
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute(
                    "INSERT INTO meta_memory (key, value, updated_at) VALUES (?, ?, ?)",
                    ("blocked", "x", _TS),
                )
        finally:
            conn.commit()
            store.close()
