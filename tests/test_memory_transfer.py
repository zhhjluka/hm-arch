"""Tests for memory export, import, and scope migration (MEM-56)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hm_arch import EventType, HMArch, MemoryConfig
from hm_arch.storage.sqlite import SQLiteStore
from hm_arch.integrations.cli.main import main
from hm_arch.integrations.config import StorageScope
from hm_arch.integrations.memory_transfer import (
    MemoryTransferError,
    export_database,
    import_bundle,
    load_export_file,
    migrate_legacy_database,
    validate_import_scope_mapping,
    write_export_file,
)


def _seed_project_memory(db_path: Path, *, project: str | None = "/workspace/app") -> str:
    with HMArch(config=MemoryConfig(db_path=str(db_path))) as memory:
        receipt = memory.add(
            "Repository uses pytest for offline tests",
            event_type=EventType.OBSERVATION,
            agent="codex",
            project=project,
            session="sess-export",
        )
    return receipt.memory_id


def _seed_global_style_memory(db_path: Path) -> str:
    with HMArch(config=MemoryConfig(db_path=str(db_path))) as memory:
        receipt = memory.add(
            "User prefers dark mode in all editors",
            agent="claude-code",
            project=None,
            session="sess-global",
        )
    return receipt.memory_id


class TestMemoryExportImport:
    def test_export_import_round_trip_preserves_provenance(self, tmp_path: Path) -> None:
        source_db = tmp_path / "source.db"
        target_db = tmp_path / "target.db"
        memory_id = _seed_project_memory(source_db)

        bundle = export_database(
            source_db,
            storage_scope=StorageScope.PROJECT,
        )
        export_path = write_export_file(bundle, tmp_path / "export.json")

        report = import_bundle(
            load_export_file(export_path),
            target_db,
            target_scope=StorageScope.PROJECT,
            project_context="/workspace/app",
        )
        assert report.total_imported > 0

        with HMArch(config=MemoryConfig(db_path=str(target_db))) as memory:
            result = memory.search("pytest offline", min_retention=0.0)

        hit = next(item for item in result.results if item.content)
        assert hit.provenance is not None
        assert hit.provenance.agent == "codex"
        assert hit.provenance.project == "/workspace/app"
        assert hit.provenance.session == "sess-export"

        with SQLiteStore(source_db) as store:
            source_rows = store.query(
                "SELECT id FROM memory_index WHERE id = ?",
                (memory_id,),
            )
        assert source_rows

    def test_unsafe_scope_mapping_rejected(self, tmp_path: Path) -> None:
        bundle = export_database(
            tmp_path / "scope.db",
            storage_scope=StorageScope.PROJECT,
        )
        with pytest.raises(MemoryTransferError, match="unsafe scope mapping"):
            validate_import_scope_mapping(
                bundle,
                target_scope=StorageScope.GLOBAL,
            )

    def test_project_tagged_import_into_global_rejected(self, tmp_path: Path) -> None:
        source_db = tmp_path / "tagged.db"
        _seed_project_memory(source_db)
        bundle = export_database(source_db, storage_scope=StorageScope.PROJECT)

        with pytest.raises(MemoryTransferError, match="project-tagged"):
            import_bundle(
                bundle,
                tmp_path / "global.db",
                target_scope=StorageScope.GLOBAL,
                allow_scope_remap=True,
            )

    def test_cross_project_import_rejected(self, tmp_path: Path) -> None:
        source_db = tmp_path / "other.db"
        _seed_project_memory(source_db, project="/other/repo")
        bundle = export_database(source_db, storage_scope=StorageScope.PROJECT)

        with pytest.raises(MemoryTransferError, match="project isolation"):
            import_bundle(
                bundle,
                tmp_path / "project.db",
                target_scope=StorageScope.PROJECT,
                project_context="/workspace/app",
            )

    def test_invalid_export_format_rejected(self, tmp_path: Path) -> None:
        bad_path = tmp_path / "bad.json"
        bad_path.write_text(json.dumps({"format": "other"}), encoding="utf-8")
        with pytest.raises(MemoryTransferError, match="unsupported export format"):
            load_export_file(bad_path)

    def test_merge_skips_duplicate_primary_keys(self, tmp_path: Path) -> None:
        source_db = tmp_path / "source-dup.db"
        target_db = tmp_path / "target-dup.db"
        _seed_project_memory(source_db, project="/workspace/app")
        bundle = export_database(source_db, storage_scope=StorageScope.PROJECT)

        first = import_bundle(
            bundle,
            target_db,
            target_scope=StorageScope.PROJECT,
            project_context="/workspace/app",
        )
        second = import_bundle(
            bundle,
            target_db,
            target_scope=StorageScope.PROJECT,
            project_context="/workspace/app",
        )
        assert first.total_imported > 0
        assert second.total_skipped > 0
        assert second.total_imported == 0


class TestLegacyMigration:
    def test_migrate_splits_global_and_project_rows(self, tmp_path: Path) -> None:
        legacy_db = tmp_path / "legacy.db"
        global_db = tmp_path / "global.db"
        project_db = tmp_path / "project.db"

        _seed_global_style_memory(legacy_db)
        _seed_project_memory(legacy_db, project=str(tmp_path / "app"))

        report = migrate_legacy_database(
            legacy_db,
            global_db=global_db,
            project_db=project_db,
            project_context=str(tmp_path / "app"),
        )
        assert report.global_rows == 1
        assert report.project_rows == 1

        with HMArch(config=MemoryConfig(db_path=str(global_db))) as memory:
            hits = memory.search("dark mode", min_retention=0.0)
        assert hits.results

        with HMArch(config=MemoryConfig(db_path=str(project_db))) as memory:
            hits = memory.search("pytest offline", min_retention=0.0)
            assert hits.results
            dark_hits = memory.search("dark mode", min_retention=0.0).results
            assert not any("dark mode" in item.content.lower() for item in dark_hits)


class TestMemoryCli:
    def test_cli_export_import(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        db_path = tmp_path / "cli.db"
        export_path = tmp_path / "bundle.json"
        target_db = tmp_path / "imported.db"

        monkeypatch.setenv("HM_ARCH_DB_PATH", str(db_path))
        with HMArch(config=MemoryConfig(db_path=str(db_path))) as memory:
            memory.add("CLI export probe", project=str(tmp_path))

        assert (
            main(
                [
                    "memory",
                    "export",
                    "-o",
                    str(export_path),
                    "--scope",
                    "project",
                    "--db",
                    str(db_path),
                ]
            )
            == 0
        )
        assert export_path.exists()
        payload = json.loads(export_path.read_text(encoding="utf-8"))
        assert payload["format"] == "hm-arch-memory-export"

        assert (
            main(
                [
                    "memory",
                    "import",
                    str(export_path),
                    "--target-scope",
                    "project",
                    "--db",
                    str(target_db),
                    "--project-context",
                    str(tmp_path),
                ]
            )
            == 0
        )

        with HMArch(config=MemoryConfig(db_path=str(target_db))) as memory:
            assert memory.search("CLI export", min_retention=0.0).results

    def test_cli_migrate_dry_run(self, tmp_path: Path) -> None:
        legacy_db = tmp_path / "legacy-cli.db"
        _seed_global_style_memory(legacy_db)
        assert (
            main(
                [
                    "memory",
                    "migrate",
                    "--from",
                    str(legacy_db),
                    "--global-db",
                    str(tmp_path / "g.db"),
                    "--project-db",
                    str(tmp_path / "p.db"),
                    "--dry-run",
                ]
            )
            == 0
        )
        assert not (tmp_path / "g.db").exists()
