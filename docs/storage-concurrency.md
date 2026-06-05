# SQLite concurrency for multi-agent access

HM-Arch stores durable memory in a local SQLite file. Multiple supported agents
(Codex, Claude Code, Hermes hooks, CLI) may open the **same database path**
from separate processes on one machine. This document describes how contention
is handled and what is guaranteed.

## How access works

Each process opens its own connection via :class:`~hm_arch.storage.sqlite.SQLiteStore`.
There is no connection pool and no distributed database layer.

On connect, HM-Arch configures SQLite for cooperative multi-process use:

| Setting | Purpose |
|---------|---------|
| `PRAGMA journal_mode=WAL` | Readers do not block the writer; one writer at a time |
| `PRAGMA busy_timeout` | Wait up to the configured timeout before failing a lock |
| `PRAGMA foreign_keys=ON` | Referential integrity on writes |
| Application lock retries | Bounded exponential backoff on transient `database is locked` errors |

File-backed databases also create sidecar files next to the `.db` path:

- `*.db-wal` — write-ahead log
- `*.db-shm` — shared-memory index for WAL

These files are normal and should be included in backups alongside the main
database file.

## Configuration

Tune concurrency behavior on :class:`~hm_arch.config.MemoryConfig`:

```python
from hm_arch import HMArch
from hm_arch.config import MemoryConfig

config = MemoryConfig(
    db_path="./.agent_memory.db",
    sqlite_busy_timeout_ms=30_000,   # default: 30 seconds
    sqlite_lock_retries=5,           # default: 5 retries after busy wait
    sqlite_lock_retry_base_delay_s=0.05,
)
memory = HMArch(config=config)
```

Lower-level callers can pass the same keyword arguments directly to
:class:`~hm_arch.storage.sqlite.SQLiteStore`.

## Expected behavior

**Supported:** Several agent processes on the **same host** reading and writing
the same configured database path (global or project store).

- Concurrent **reads** proceed while a write is in progress (WAL mode).
- Concurrent **writes** serialize; later writers wait, retry, then succeed or
  raise `sqlite3.OperationalError` after retries are exhausted.
- Adapter hooks (CLI, Codex, Claude Code) **fail open** if storage still errors
  after retries, returning a structured error instead of crashing the host.

**Not supported:**

- Multi-machine or cloud sync of one database
- Automatic merge or conflict resolution across copies
- High-frequency parallel writers (SQLite remains single-writer)

See also :doc:`memory-sharing-policies` for global vs project store isolation.

## Operational guidance

1. Point all agents at the same resolved path (`HM_ARCH_DB_PATH`,
   `HM_ARCH_GLOBAL_DB_PATH`, or `HM_ARCH_PROJECT_DB_PATH`).
2. Keep write transactions short; import/migrate uses `BEGIN IMMEDIATE` for
   atomic bundles.
3. Back up the `.db`, `-wal`, and `-shm` files together when the database is
   quiescent or via `hm-arch memory export`.
4. If lock errors persist, check for a stuck process holding a long transaction
   or increase `sqlite_busy_timeout_ms` / `sqlite_lock_retries`.

## Limitations

- `:memory:` databases are single-process only (used in tests).
- WAL is validated on file paths; in-memory journal mode remains `memory`.
- Extreme write contention can still fail after all retries; that is expected
  SQLite behavior, not data corruption.
