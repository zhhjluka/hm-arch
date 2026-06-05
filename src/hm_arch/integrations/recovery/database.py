"""SQLite backup, restore, and non-destructive repair helpers."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from hm_arch.integrations.config import IntegrationConfig, StorageScope
from hm_arch.integrations.management.types import Diagnostic, DiagnosticLevel
from hm_arch.storage.migrations import CURRENT_SCHEMA_VERSION, apply_migrations
from hm_arch.storage.sqlite import REQUIRED_TABLES, SQLiteStore

BACKUP_MANIFEST = "manifest.json"
BACKUP_FORMAT = "hm-arch-db-backup"
BACKUP_FORMAT_VERSION = 1


class DatabaseRecoveryError(RuntimeError):
    """Raised when backup, restore, or repair cannot complete safely."""


@dataclass(frozen=True)
class BackupReport:
    """Summary of a filesystem database backup."""

    source_db: str
    backup_dir: str
    files_copied: tuple[str, ...]
    memory_row_count: int
    storage_scope: StorageScope


@dataclass(frozen=True)
class RestoreReport:
    """Summary of restoring a filesystem database backup."""

    backup_dir: str
    target_db: str
    files_restored: tuple[str, ...]
    replaced_existing: bool


@dataclass(frozen=True)
class RepairReport:
    """Summary of a non-destructive database repair."""

    db_path: str
    integrity_ok: bool
    schema_version: int
    vacuumed: bool
    checkpointed: bool
    issues: tuple[str, ...] = ()


def _db_sidecar_paths(db_path: Path) -> tuple[Path, ...]:
    return (
        db_path,
        Path(f"{db_path}-wal"),
        Path(f"{db_path}-shm"),
    )


def backup_database(
    db_path: str | Path,
    output_dir: str | Path,
    *,
    storage_scope: StorageScope,
) -> BackupReport:
    """Copy the SQLite database and WAL sidecars into *output_dir*."""
    source = Path(db_path)
    if not source.exists():
        raise DatabaseRecoveryError(f"database does not exist: {source}")

    dest_dir = Path(output_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Checkpoint WAL so the main file is as complete as possible.
    _checkpoint_wal(source)

    copied: list[str] = []
    for sidecar in _db_sidecar_paths(source):
        if not sidecar.exists():
            continue
        target = dest_dir / sidecar.name
        shutil.copy2(sidecar, target)
        copied.append(sidecar.name)

    if not copied:
        raise DatabaseRecoveryError(f"no database files found at {source}")

    memory_rows = 0
    with SQLiteStore(source) as store:
        rows = store.query("SELECT COUNT(*) AS count FROM memory_index")
        memory_rows = int(rows[0]["count"]) if rows else 0

    manifest = {
        "format": BACKUP_FORMAT,
        "format_version": BACKUP_FORMAT_VERSION,
        "backed_up_at": datetime.now(tz=timezone.utc).isoformat(),
        "source_db": str(source),
        "storage_scope": storage_scope.value,
        "schema_version": CURRENT_SCHEMA_VERSION,
        "files": copied,
        "memory_row_count": memory_rows,
    }
    (dest_dir / BACKUP_MANIFEST).write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return BackupReport(
        source_db=str(source),
        backup_dir=str(dest_dir),
        files_copied=tuple(copied),
        memory_row_count=memory_rows,
        storage_scope=storage_scope,
    )


def restore_database(
    backup_dir: str | Path,
    target_db: str | Path,
    *,
    confirm: bool,
) -> RestoreReport:
    """Restore a filesystem backup created by :func:`backup_database`."""
    if not confirm:
        raise DatabaseRecoveryError(
            "restore requires --confirm to overwrite the destination database"
        )

    source_dir = Path(backup_dir)
    manifest_path = source_dir / BACKUP_MANIFEST
    if not manifest_path.exists():
        raise DatabaseRecoveryError(
            f"backup manifest missing at {manifest_path}; expected {BACKUP_MANIFEST}"
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != BACKUP_FORMAT:
        raise DatabaseRecoveryError(
            f"unsupported backup format: {manifest.get('format')!r}"
        )

    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise DatabaseRecoveryError("backup manifest contains no files")

    main_name = _main_db_filename(files)
    if main_name is None:
        raise DatabaseRecoveryError("backup manifest does not list a .db file")

    backup_sources: list[tuple[str, Path]] = []
    for name in files:
        src = source_dir / str(name)
        if not src.exists():
            raise DatabaseRecoveryError(f"backup file missing: {src}")
        backup_sources.append((str(name), src))

    target = Path(target_db)
    target.parent.mkdir(parents=True, exist_ok=True)
    replaced = target.exists()

    restored: list[str] = []
    restored_suffixes: set[str] = set()
    with tempfile.TemporaryDirectory(
        prefix=".hm-arch-restore-",
        dir=target.parent,
    ) as staging_dir_name:
        staging_dir = Path(staging_dir_name)
        staged_main = staging_dir / target.name

        for name, src in backup_sources:
            suffix = name[len(main_name) :]
            staged_path = staging_dir / (target.name + suffix)
            shutil.copy2(src, staged_path)
            restored.append(name)
            restored_suffixes.add(suffix)

        with SQLiteStore(staged_main) as store:
            integrity = _integrity_check(store)
            if integrity != "ok":
                raise DatabaseRecoveryError(
                    f"restored database failed integrity check: {integrity}"
                )

        for name, _src in backup_sources:
            suffix = name[len(main_name) :]
            staged_path = staging_dir / (target.name + suffix)
            final_path = Path(str(target) + suffix)
            os.replace(staged_path, final_path)

    for sidecar in _db_sidecar_paths(target):
        suffix = "" if sidecar == target else sidecar.name[len(target.name) :]
        if suffix not in restored_suffixes and sidecar.exists():
            sidecar.unlink()

    return RestoreReport(
        backup_dir=str(source_dir),
        target_db=str(target),
        files_restored=tuple(restored),
        replaced_existing=replaced,
    )


def repair_database(
    db_path: str | Path,
    *,
    vacuum: bool = False,
) -> RepairReport:
    """Run non-destructive integrity checks and schema repair on *db_path*."""
    path = Path(db_path)
    if not path.exists():
        raise DatabaseRecoveryError(f"database does not exist: {path}")

    checkpointed = _checkpoint_wal(path)

    with SQLiteStore(path) as store:
        integrity = _integrity_check(store)
        issues: list[str] = []
        if integrity != "ok":
            issues.append(integrity)

        if integrity == "ok":
            store.initialize_schema()
            apply_migrations(store)

        schema_rows = store.query("SELECT version FROM schema_version LIMIT 1")
        schema_version = (
            int(schema_rows[0]["version"]) if schema_rows else CURRENT_SCHEMA_VERSION
        )

        vacuumed = False
        if vacuum and integrity == "ok":
            store.execute("VACUUM")
            vacuumed = True

    return RepairReport(
        db_path=str(path),
        integrity_ok=integrity == "ok",
        schema_version=schema_version,
        vacuumed=vacuumed,
        checkpointed=checkpointed,
        issues=tuple(issues),
    )


def storage_diagnostics(config: IntegrationConfig | None = None) -> tuple[Diagnostic, ...]:
    """Return storage permission and integrity diagnostics for configured scopes."""
    cfg = config or IntegrationConfig()
    diagnostics: list[Diagnostic] = []
    for scope in (StorageScope.PROJECT, StorageScope.GLOBAL):
        db_path = Path(cfg.resolve_db_path(expanduser=os.path.expanduser, scope=scope))
        diagnostics.extend(_diagnose_db_path(db_path, scope=scope))
    return tuple(diagnostics)


def _diagnose_db_path(db_path: Path, *, scope: StorageScope) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    parent = db_path.parent

    if not parent.exists():
        diagnostics.append(
            Diagnostic(
                code=f"storage.{scope.value}.parent_missing",
                level=DiagnosticLevel.WARNING,
                message=f"Storage parent directory does not exist: {parent}",
                remedy=f"Create {parent} or run hm-arch memory repair --scope {scope.value}",
            )
        )
        return diagnostics

    if not os.access(parent, os.W_OK):
        diagnostics.append(
            Diagnostic(
                code=f"storage.{scope.value}.permission_denied",
                level=DiagnosticLevel.ERROR,
                message=f"Storage directory is not writable: {parent}",
                remedy=f"Fix permissions on {parent} or choose a writable database path.",
            )
        )

    if not db_path.exists():
        diagnostics.append(
            Diagnostic(
                code=f"storage.{scope.value}.db_missing",
                level=DiagnosticLevel.INFO,
                message=f"No database file yet for {scope.value} scope at {db_path}.",
            )
        )
        return diagnostics

    try:
        with SQLiteStore(db_path) as store:
            integrity = _integrity_check(store)
            row_count = store.query("SELECT COUNT(*) AS count FROM memory_index")
            count = int(row_count[0]["count"]) if row_count else 0
    except (OSError, sqlite3.Error) as exc:
        diagnostics.append(
            Diagnostic(
                code=f"storage.{scope.value}.open_failed",
                level=DiagnosticLevel.ERROR,
                message=f"Could not open database at {db_path}: {exc}",
                remedy=f"Run: hm-arch memory repair --scope {scope.value}",
            )
        )
        return diagnostics

    if integrity != "ok":
        diagnostics.append(
            Diagnostic(
                code=f"storage.{scope.value}.integrity_failed",
                level=DiagnosticLevel.ERROR,
                message=f"Integrity check failed for {db_path}: {integrity}",
                remedy=(
                    f"Run: hm-arch memory repair --scope {scope.value}; "
                    "restore from hm-arch memory backup if repair cannot recover data."
                ),
            )
        )
    else:
        missing_tables = _missing_tables(db_path)
        if missing_tables:
            diagnostics.append(
                Diagnostic(
                    code=f"storage.{scope.value}.schema_incomplete",
                    level=DiagnosticLevel.WARNING,
                    message=(
                        f"Database at {db_path} is missing tables: "
                        f"{', '.join(sorted(missing_tables))}."
                    ),
                    remedy=f"Run: hm-arch memory repair --scope {scope.value}",
                )
            )
        else:
            diagnostics.append(
                Diagnostic(
                    code=f"storage.{scope.value}.healthy",
                    level=DiagnosticLevel.INFO,
                    message=(
                        f"Database at {db_path} passed integrity check "
                        f"({count} memories)."
                    ),
                )
            )
    return diagnostics


def _missing_tables(db_path: Path) -> set[str]:
    with SQLiteStore(db_path) as store:
        rows = store.query(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    present = {str(row["name"]) for row in rows}
    return set(REQUIRED_TABLES) - present


def _integrity_check(store: SQLiteStore) -> str:
    rows = store.query("PRAGMA integrity_check")
    if not rows:
        return "integrity_check returned no rows"
    result = str(rows[0][0])
    return result


def _main_db_filename(files: list[object]) -> str | None:
    for name in files:
        text = str(name)
        if text.endswith(".db") and not text.endswith((".db-wal", ".db-shm")):
            return text
    return None


def _checkpoint_wal(db_path: Path) -> bool:
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.commit()
        finally:
            conn.close()
        return True
    except sqlite3.Error:
        return False
