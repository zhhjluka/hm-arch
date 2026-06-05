"""Memory export, import, and single-store to dual-store migration (MEM-56).

Portable exports preserve SQLite rows and provenance columns. Imports validate
format, scope mappings, and provenance before writing so corrupt bundles cannot
damage target stores.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from hm_arch.storage.migrations import CURRENT_SCHEMA_VERSION, apply_migrations
from hm_arch.storage.sqlite import REQUIRED_TABLES, SQLiteStore

from .config import IntegrationConfig, StorageScope

EXPORT_FORMAT = "hm-arch-memory-export"
EXPORT_FORMAT_VERSION = 1

_EXPORT_TABLES: tuple[str, ...] = tuple(sorted(REQUIRED_TABLES))

# Parent rows must be inserted before child tables (FK order).
_IMPORT_TABLE_ORDER: tuple[str, ...] = (
    "memory_index",
    "episodes",
    "semantics",
    "skills",
    "meta_memory",
    "review_queue",
    "consolidation_log",
)

_UNSAFE_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_MAX_PROVENANCE_FIELD_LEN = 512


class MemoryTransferError(ValueError):
    """Raised when export/import/migrate validation fails."""


@dataclass(frozen=True)
class ExportBundle:
    """In-memory representation of a portable memory export."""

    storage_scope: StorageScope
    schema_version: int
    tables: dict[str, list[dict[str, Any]]]
    source_db: str | None = None
    exported_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": EXPORT_FORMAT,
            "format_version": EXPORT_FORMAT_VERSION,
            "exported_at": self.exported_at
            or datetime.now(tz=timezone.utc).isoformat(),
            "schema_version": self.schema_version,
            "storage_scope": self.storage_scope.value,
            "source_db": self.source_db,
            "tables": self.tables,
        }


@dataclass(frozen=True)
class ImportReport:
    """Summary of rows written during import."""

    target_scope: StorageScope
    target_db: str
    rows_imported: dict[str, int]
    rows_skipped: dict[str, int]

    @property
    def total_imported(self) -> int:
        return sum(self.rows_imported.values())

    @property
    def total_skipped(self) -> int:
        return sum(self.rows_skipped.values())


@dataclass(frozen=True)
class MigrateReport:
    """Summary of a legacy single-database split migration."""

    source_db: str
    global_db: str
    project_db: str
    global_rows: int
    project_rows: int
    project_context: str


def export_database(
    db_path: str | Path,
    *,
    storage_scope: StorageScope,
    source_hint: str | None = None,
) -> ExportBundle:
    """Export all PRD tables from *db_path* into a portable bundle."""
    path = Path(db_path)
    tables: dict[str, list[dict[str, Any]]] = {}
    with SQLiteStore(path) as store:
        store.initialize_schema()
        schema_rows = store.query("SELECT version FROM schema_version LIMIT 1")
        schema_version = (
            int(schema_rows[0]["version"]) if schema_rows else CURRENT_SCHEMA_VERSION
        )
        for table in _EXPORT_TABLES:
            rows = store.query(f"SELECT * FROM {table}")
            tables[table] = [_row_to_dict(row) for row in rows]

    return ExportBundle(
        storage_scope=storage_scope,
        schema_version=schema_version,
        tables=tables,
        source_db=source_hint or str(path),
        exported_at=datetime.now(tz=timezone.utc).isoformat(),
    )


def write_export_file(bundle: ExportBundle, output_path: str | Path) -> Path:
    """Serialize *bundle* to JSON at *output_path*."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(bundle.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def load_export_file(path: str | Path) -> ExportBundle:
    """Parse and validate an export file from disk."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return parse_export_payload(payload)


def parse_export_payload(payload: Mapping[str, Any]) -> ExportBundle:
    """Validate *payload* structure and return an :class:`ExportBundle`."""
    if payload.get("format") != EXPORT_FORMAT:
        raise MemoryTransferError(
            f"unsupported export format: {payload.get('format')!r}"
        )
    if payload.get("format_version") != EXPORT_FORMAT_VERSION:
        raise MemoryTransferError(
            f"unsupported format_version: {payload.get('format_version')!r}"
        )

    scope_raw = payload.get("storage_scope")
    try:
        storage_scope = StorageScope(str(scope_raw))
    except ValueError as exc:
        raise MemoryTransferError(f"invalid storage_scope: {scope_raw!r}") from exc

    tables_raw = payload.get("tables")
    if not isinstance(tables_raw, dict):
        raise MemoryTransferError("export missing tables object")

    tables: dict[str, list[dict[str, Any]]] = {}
    for table in _EXPORT_TABLES:
        rows = tables_raw.get(table)
        if rows is None:
            tables[table] = []
        elif not isinstance(rows, list):
            raise MemoryTransferError(f"tables[{table!r}] must be a list")
        else:
            tables[table] = [_require_row_dict(row, table) for row in rows]

    schema_version = int(payload.get("schema_version", CURRENT_SCHEMA_VERSION))
    return ExportBundle(
        storage_scope=storage_scope,
        schema_version=schema_version,
        tables=tables,
        source_db=_optional_str(payload.get("source_db")),
        exported_at=_optional_str(payload.get("exported_at")),
    )


def validate_import_scope_mapping(
    bundle: ExportBundle,
    *,
    target_scope: StorageScope,
    allow_scope_remap: bool = False,
) -> None:
    """Reject unsafe scope remappings unless explicitly allowed."""
    if bundle.storage_scope is target_scope:
        return
    if allow_scope_remap:
        return
    raise MemoryTransferError(
        f"unsafe scope mapping: export is {bundle.storage_scope.value!r} "
        f"but import target is {target_scope.value!r}; "
        "pass --allow-scope-remap to override"
    )


def validate_provenance_rows(
    bundle: ExportBundle,
    *,
    target_scope: StorageScope,
    project_context: str | None = None,
    allow_cross_scope: bool = False,
) -> None:
    """Validate provenance fields and project isolation rules on import."""
    rows = bundle.tables.get("memory_index", [])
    normalized_context = (
        _normalize_project_id(project_context) if project_context else None
    )

    for row in rows:
        _validate_provenance_field("provenance_agent", row.get("provenance_agent"))
        _validate_provenance_field(
            "provenance_session", row.get("provenance_session")
        )
        _validate_provenance_field("memory_type", row.get("memory_type"))
        project_value = row.get("provenance_project")
        if project_value is not None:
            _validate_provenance_field("provenance_project", project_value)

        if allow_cross_scope:
            continue

        tagged_project = (
            _normalize_project_id(str(project_value))
            if project_value is not None
            else None
        )

        if target_scope is StorageScope.GLOBAL and tagged_project is not None:
            raise MemoryTransferError(
                "cannot import project-tagged memory into global store "
                f"(memory_id={row.get('id')!r}, project={project_value!r}); "
                "use --allow-cross-scope only when you accept broader sharing"
            )

        if (
            target_scope is StorageScope.PROJECT
            and tagged_project is not None
            and normalized_context is not None
            and tagged_project != normalized_context
        ):
            raise MemoryTransferError(
                "project isolation violation: memory "
                f"{row.get('id')!r} belongs to {project_value!r}, "
                f"not {project_context!r}"
            )


def import_bundle(
    bundle: ExportBundle,
    db_path: str | Path,
    *,
    target_scope: StorageScope,
    mode: str = "merge",
    allow_scope_remap: bool = False,
    allow_cross_scope: bool = False,
    project_context: str | None = None,
) -> ImportReport:
    """Import *bundle* into *db_path* after validation."""
    if mode not in {"merge", "replace"}:
        raise MemoryTransferError(f"unsupported import mode: {mode!r}")

    validate_import_scope_mapping(
        bundle,
        target_scope=target_scope,
        allow_scope_remap=allow_scope_remap,
    )
    validate_provenance_rows(
        bundle,
        target_scope=target_scope,
        project_context=project_context,
        allow_cross_scope=allow_cross_scope,
    )
    _validate_referential_integrity(bundle)

    path = Path(db_path)
    imported: dict[str, int] = {table: 0 for table in _EXPORT_TABLES}
    skipped: dict[str, int] = {table: 0 for table in _EXPORT_TABLES}

    with SQLiteStore(path) as store:
        store.initialize_schema()
        apply_migrations(store)
        if mode == "replace":
            _clear_export_tables(store)

        for table in _IMPORT_TABLE_ORDER:
            for row in bundle.tables.get(table, []):
                written = _insert_row(store, table, row, mode=mode)
                if written:
                    imported[table] += 1
                else:
                    skipped[table] += 1

    return ImportReport(
        target_scope=target_scope,
        target_db=str(path),
        rows_imported=imported,
        rows_skipped=skipped,
    )


def migrate_legacy_database(
    source_db: str | Path,
    *,
    global_db: str | Path,
    project_db: str | Path,
    project_context: str | None = None,
    dry_run: bool = False,
) -> MigrateReport:
    """Split a legacy single-project database into global and project stores.

    Rows with no ``provenance_project`` are treated as global user memory.
    Rows with a project tag are written to the project store when the tag
    matches *project_context* (defaults to the current working directory).
    """
    source_path = Path(source_db)
    context = project_context or str(Path.cwd().resolve())
    normalized_context = _normalize_project_id(context)

    bundle = export_database(
        source_path,
        storage_scope=StorageScope.PROJECT,
        source_hint=str(source_path),
    )

    global_rows = bundle.tables.get("memory_index", [])
    global_ids = {
        row["id"]
        for row in global_rows
        if row.get("provenance_project") in (None, "")
    }
    project_ids = {
        row["id"]
        for row in global_rows
        if row.get("provenance_project") not in (None, "")
        and _normalize_project_id(str(row["provenance_project"]))
        == normalized_context
    }
    unknown_project_ids = {
        row["id"]
        for row in global_rows
        if row.get("provenance_project") not in (None, "")
        and row["id"] not in project_ids
    }
    if unknown_project_ids:
        raise MemoryTransferError(
            f"{len(unknown_project_ids)} memories belong to other projects; "
            f"re-run with --project-context matching the source repo or export "
            "those rows manually"
        )

    global_bundle = _subset_bundle(
        bundle,
        global_ids,
        StorageScope.GLOBAL,
        include_auxiliary_tables=False,
    )
    project_bundle = _subset_bundle(
        bundle,
        project_ids,
        StorageScope.PROJECT,
        include_auxiliary_tables=True,
    )

    if not dry_run:
        if global_ids:
            import_bundle(
                global_bundle,
                global_db,
                target_scope=StorageScope.GLOBAL,
                allow_scope_remap=True,
                allow_cross_scope=True,
            )
        if project_ids:
            import_bundle(
                project_bundle,
                project_db,
                target_scope=StorageScope.PROJECT,
                allow_scope_remap=True,
                allow_cross_scope=True,
                project_context=context,
            )

    return MigrateReport(
        source_db=str(source_path),
        global_db=str(global_db),
        project_db=str(project_db),
        global_rows=len(global_ids),
        project_rows=len(project_ids),
        project_context=context,
    )


def resolve_transfer_db_path(
    config: IntegrationConfig,
    *,
    scope: StorageScope,
    explicit_db: str | None = None,
) -> str:
    """Resolve the SQLite path used by transfer commands."""
    if explicit_db:
        return explicit_db
    return config.resolve_db_path(scope=scope)


def _subset_bundle(
    bundle: ExportBundle,
    memory_ids: set[str],
    storage_scope: StorageScope,
    *,
    include_auxiliary_tables: bool,
) -> ExportBundle:
    tables: dict[str, list[dict[str, Any]]] = {}
    for table in _EXPORT_TABLES:
        rows = bundle.tables.get(table, [])
        if table == "memory_index":
            tables[table] = [row for row in rows if row.get("id") in memory_ids]
        elif table in {"episodes", "semantics", "review_queue"}:
            tables[table] = [
                row for row in rows if row.get("memory_id") in memory_ids
            ]
        elif include_auxiliary_tables:
            tables[table] = list(rows)
        else:
            tables[table] = []

    return ExportBundle(
        storage_scope=storage_scope,
        schema_version=bundle.schema_version,
        tables=tables,
        source_db=bundle.source_db,
    )


def _validate_referential_integrity(bundle: ExportBundle) -> None:
    memory_ids = {row["id"] for row in bundle.tables.get("memory_index", [])}
    for table, key in (
        ("episodes", "memory_id"),
        ("semantics", "memory_id"),
        ("review_queue", "memory_id"),
    ):
        for row in bundle.tables.get(table, []):
            ref = row.get(key)
            if ref is not None and ref not in memory_ids:
                raise MemoryTransferError(
                    f"{table} row references unknown memory_id {ref!r}"
                )


def _clear_export_tables(store: SQLiteStore) -> None:
    for table in reversed(_IMPORT_TABLE_ORDER):
        store.execute(f"DELETE FROM {table}")


def _insert_row(
    store: SQLiteStore,
    table: str,
    row: Mapping[str, Any],
    *,
    mode: str,
) -> bool:
    columns = list(row.keys())
    placeholders = ", ".join("?" for _ in columns)
    col_list = ", ".join(columns)
    values = tuple(row[col] for col in columns)

    if mode == "merge":
        sql = (
            f"INSERT OR IGNORE INTO {table} ({col_list}) "
            f"VALUES ({placeholders})"
        )
        cursor = store.execute(sql, values)
        return cursor.rowcount > 0

    sql = f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})"
    store.execute(sql, values)
    return True


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _require_row_dict(value: Any, table: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MemoryTransferError(f"tables[{table!r}] rows must be objects")
    return dict(value)


def _validate_provenance_field(name: str, value: object) -> None:
    if value is None:
        return
    text = str(value)
    if not text.strip():
        raise MemoryTransferError(f"{name} must not be blank when set")
    if len(text) > _MAX_PROVENANCE_FIELD_LEN:
        raise MemoryTransferError(f"{name} exceeds {_MAX_PROVENANCE_FIELD_LEN} chars")
    if _UNSAFE_CONTROL_CHARS.search(text):
        raise MemoryTransferError(f"{name} contains unsafe control characters")


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_project_id(value: str) -> str:
    text = value.strip()
    try:
        return str(Path(text).resolve())
    except (OSError, RuntimeError):
        return text
