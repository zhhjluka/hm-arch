"""``hm-arch memory export|import|migrate`` handlers (MEM-56)."""

from __future__ import annotations

import argparse
import json
import sys

from hm_arch.integrations.config import IntegrationConfig, StorageScope
from hm_arch.integrations.management.types import DiagnosticLevel
from hm_arch.integrations.memory_transfer import (
    MemoryTransferError,
    export_database,
    import_bundle,
    load_export_file,
    migrate_legacy_database,
    resolve_transfer_db_path,
    write_export_file,
)
from hm_arch.integrations.recovery.database import (
    DatabaseRecoveryError,
    backup_database,
    repair_database,
    restore_database,
)
from hm_arch.integrations.recovery.diagnostics import RecoveryLogger, RecoveryPhase


def add_memory_parsers(subparsers: argparse._SubParsersAction) -> None:
    memory_parser = subparsers.add_parser(
        "memory",
        help="Export, import, or migrate HM-Arch SQLite memory stores.",
    )
    memory_sub = memory_parser.add_subparsers(dest="memory_command", required=True)

    export_parser = memory_sub.add_parser(
        "export",
        help="Export a SQLite memory database to a portable JSON bundle.",
    )
    export_parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Destination JSON file path.",
    )
    export_parser.add_argument(
        "--scope",
        choices=[s.value for s in StorageScope],
        default=StorageScope.PROJECT.value,
        help="Storage scope label stored in the export (default: project).",
    )
    export_parser.add_argument(
        "--db",
        help="SQLite database path (defaults from integration config).",
    )

    import_parser = memory_sub.add_parser(
        "import",
        help="Import a portable JSON bundle into a SQLite memory database.",
    )
    import_parser.add_argument(
        "bundle",
        help="Path to an export JSON file.",
    )
    import_parser.add_argument(
        "--target-scope",
        choices=[s.value for s in StorageScope],
        required=True,
        help="Scope of the destination store (project or global).",
    )
    import_parser.add_argument(
        "--db",
        help="Destination SQLite path (defaults from integration config).",
    )
    import_parser.add_argument(
        "--mode",
        choices=("merge", "replace"),
        default="merge",
        help="merge skips existing primary keys; replace overwrites rows.",
    )
    import_parser.add_argument(
        "--project-context",
        help="Project path used for isolation checks (default: cwd).",
    )
    import_parser.add_argument(
        "--allow-scope-remap",
        action="store_true",
        help="Allow import when export scope differs from --target-scope.",
    )
    import_parser.add_argument(
        "--allow-cross-scope",
        action="store_true",
        help="Allow project-tagged rows into a global store (use with care).",
    )

    migrate_parser = memory_sub.add_parser(
        "migrate",
        help="Split a legacy single-store database into global and project stores.",
    )
    migrate_parser.add_argument(
        "--from",
        dest="source_db",
        required=True,
        help="Legacy single-project SQLite database path.",
    )
    migrate_parser.add_argument(
        "--global-db",
        help="Destination global SQLite path (config default if omitted).",
    )
    migrate_parser.add_argument(
        "--project-db",
        help="Destination project SQLite path (config default if omitted).",
    )
    migrate_parser.add_argument(
        "--project-context",
        help="Project identifier for tagging rows (default: cwd).",
    )
    migrate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report the split without writing destination databases.",
    )

    backup_parser = memory_sub.add_parser(
        "backup",
        help="Create a filesystem backup of a SQLite memory database and WAL sidecars.",
    )
    backup_parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Destination backup directory.",
    )
    backup_parser.add_argument(
        "--scope",
        choices=[s.value for s in StorageScope],
        default=StorageScope.PROJECT.value,
        help="Storage scope label for the backup manifest (default: project).",
    )
    backup_parser.add_argument(
        "--db",
        help="SQLite database path (defaults from integration config).",
    )

    restore_parser = memory_sub.add_parser(
        "restore",
        help="Restore a filesystem backup into a SQLite memory database.",
    )
    restore_parser.add_argument(
        "backup_dir",
        help="Backup directory created by hm-arch memory backup.",
    )
    restore_parser.add_argument(
        "--target-scope",
        choices=[s.value for s in StorageScope],
        required=True,
        help="Scope of the destination store (project or global).",
    )
    restore_parser.add_argument(
        "--db",
        help="Destination SQLite path (defaults from integration config).",
    )
    restore_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required to overwrite an existing destination database.",
    )

    repair_parser = memory_sub.add_parser(
        "repair",
        help="Run non-destructive integrity checks and schema repair.",
    )
    repair_parser.add_argument(
        "--scope",
        choices=[s.value for s in StorageScope],
        default=StorageScope.PROJECT.value,
        help="Storage scope to repair (default: project).",
    )
    repair_parser.add_argument(
        "--db",
        help="SQLite database path (defaults from integration config).",
    )
    repair_parser.add_argument(
        "--vacuum",
        action="store_true",
        help="Run VACUUM after a successful integrity check.",
    )


def run_memory_command(args: argparse.Namespace) -> int:
    if args.memory_command == "export":
        return _run_export(args)
    if args.memory_command == "import":
        return _run_import(args)
    if args.memory_command == "migrate":
        return _run_migrate(args)
    if args.memory_command == "backup":
        return _run_backup(args)
    if args.memory_command == "restore":
        return _run_restore(args)
    if args.memory_command == "repair":
        return _run_repair(args)
    return 2


def _integration_config() -> IntegrationConfig:
    return IntegrationConfig()


def _run_export(args: argparse.Namespace) -> int:
    config = _integration_config()
    scope = StorageScope(args.scope)
    db_path = resolve_transfer_db_path(config, scope=scope, explicit_db=args.db)
    try:
        bundle = export_database(db_path, storage_scope=scope, source_hint=db_path)
        out_path = write_export_file(bundle, args.output)
    except (MemoryTransferError, OSError, ValueError) as exc:
        print(f"memory export failed: {exc}", file=sys.stderr)
        return 1

    row_count = sum(len(rows) for rows in bundle.tables.values())
    print(
        f"Exported {row_count} rows from {db_path} "
        f"({scope.value}) -> {out_path}",
        file=sys.stderr,
    )
    return 0


def _run_import(args: argparse.Namespace) -> int:
    config = _integration_config()
    target_scope = StorageScope(args.target_scope)
    db_path = resolve_transfer_db_path(
        config,
        scope=target_scope,
        explicit_db=args.db,
    )
    try:
        bundle = load_export_file(args.bundle)
        report = import_bundle(
            bundle,
            db_path,
            target_scope=target_scope,
            mode=args.mode,
            allow_scope_remap=args.allow_scope_remap,
            allow_cross_scope=args.allow_cross_scope,
            project_context=args.project_context,
        )
    except (MemoryTransferError, json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"memory import failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"Imported {report.total_imported} rows into {db_path} "
        f"({target_scope.value}); skipped {report.total_skipped}",
        file=sys.stderr,
    )
    return 0


def _run_migrate(args: argparse.Namespace) -> int:
    config = _integration_config()
    global_db = args.global_db or resolve_transfer_db_path(
        config,
        scope=StorageScope.GLOBAL,
    )
    project_db = args.project_db or resolve_transfer_db_path(
        config,
        scope=StorageScope.PROJECT,
    )
    try:
        report = migrate_legacy_database(
            args.source_db,
            global_db=global_db,
            project_db=project_db,
            project_context=args.project_context,
            dry_run=args.dry_run,
        )
    except (MemoryTransferError, OSError, ValueError) as exc:
        print(f"memory migrate failed: {exc}", file=sys.stderr)
        return 1

    suffix = " (dry run)" if args.dry_run else ""
    print(
        f"Migrated {report.source_db}{suffix}: "
        f"{report.global_rows} global rows -> {report.global_db}, "
        f"{report.project_rows} project rows -> {report.project_db} "
        f"(context={report.project_context})",
        file=sys.stderr,
    )
    return 0


def _run_backup(args: argparse.Namespace) -> int:
    config = _integration_config()
    scope = StorageScope(args.scope)
    db_path = resolve_transfer_db_path(config, scope=scope, explicit_db=args.db)
    logger = RecoveryLogger(RecoveryPhase.BACKUP)
    try:
        report = backup_database(db_path, args.output, storage_scope=scope)
    except (DatabaseRecoveryError, OSError) as exc:
        logger.log("backup.failed", level=DiagnosticLevel.ERROR, message=str(exc))
        print(f"memory backup failed: {exc}", file=sys.stderr)
        return 1

    logger.log(
        "backup.completed",
        level=DiagnosticLevel.INFO,
        message=f"Backed up {report.memory_row_count} memories from {report.source_db}",
        files=list(report.files_copied),
        backup_dir=report.backup_dir,
    )
    print(
        f"Backed up {report.memory_row_count} memories from {report.source_db} "
        f"-> {report.backup_dir} ({', '.join(report.files_copied)})",
        file=sys.stderr,
    )
    return 0


def _run_restore(args: argparse.Namespace) -> int:
    config = _integration_config()
    target_scope = StorageScope(args.target_scope)
    db_path = resolve_transfer_db_path(
        config,
        scope=target_scope,
        explicit_db=args.db,
    )
    logger = RecoveryLogger(RecoveryPhase.RESTORE)
    try:
        report = restore_database(args.backup_dir, db_path, confirm=args.confirm)
    except (DatabaseRecoveryError, OSError) as exc:
        logger.log("restore.failed", level=DiagnosticLevel.ERROR, message=str(exc))
        print(f"memory restore failed: {exc}", file=sys.stderr)
        return 1

    logger.log(
        "restore.completed",
        level=DiagnosticLevel.INFO,
        message=f"Restored backup into {report.target_db}",
        files=list(report.files_restored),
        replaced_existing=report.replaced_existing,
    )
    print(
        f"Restored {len(report.files_restored)} file(s) into {report.target_db}"
        f"{' (replaced existing database)' if report.replaced_existing else ''}",
        file=sys.stderr,
    )
    return 0


def _run_repair(args: argparse.Namespace) -> int:
    config = _integration_config()
    scope = StorageScope(args.scope)
    db_path = resolve_transfer_db_path(config, scope=scope, explicit_db=args.db)
    logger = RecoveryLogger(RecoveryPhase.REPAIR)
    try:
        report = repair_database(db_path, vacuum=args.vacuum)
    except (DatabaseRecoveryError, OSError) as exc:
        logger.log("repair.failed", level=DiagnosticLevel.ERROR, message=str(exc))
        print(f"memory repair failed: {exc}", file=sys.stderr)
        return 1

    if not report.integrity_ok:
        for issue in report.issues:
            logger.log(
                "repair.integrity_failed",
                level=DiagnosticLevel.ERROR,
                message=issue,
                db_path=report.db_path,
            )
        print(
            f"memory repair failed integrity check for {report.db_path}: "
            f"{'; '.join(report.issues)}",
            file=sys.stderr,
        )
        return 1

    logger.log(
        "repair.completed",
        level=DiagnosticLevel.INFO,
        message=f"Repaired database at {report.db_path}",
        schema_version=report.schema_version,
        vacuumed=report.vacuumed,
        checkpointed=report.checkpointed,
    )
    print(
        f"Repaired {report.db_path} (schema v{report.schema_version}"
        f"{', vacuumed' if report.vacuumed else ''}"
        f"{', checkpointed' if report.checkpointed else ''})",
        file=sys.stderr,
    )
    return 0
