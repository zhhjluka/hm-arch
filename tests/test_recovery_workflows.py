"""Recovery workflow tests for doctor --fix, backup, restore, and repair (MEM-60)."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from hm_arch import EventType, HMArch, MemoryConfig
from hm_arch.integrations.cli.main import main
from hm_arch.integrations.config import StorageScope
from hm_arch.integrations.recovery.database import (
    DatabaseRecoveryError,
    backup_database,
    repair_database,
    restore_database,
    storage_diagnostics,
)
from hm_arch.integrations.recovery.doctor_fix import apply_safe_fixes
from hm_arch.storage.sqlite import SQLiteStore


def _seed_memory(db_path: Path) -> str:
    with HMArch(config=MemoryConfig(db_path=str(db_path))) as memory:
        receipt = memory.add(
            "Recovery workflow test memory",
            event_type=EventType.OBSERVATION,
            agent="codex",
            project="/workspace/recovery",
            session="sess-recovery",
        )
    return receipt.memory_id


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


@pytest.fixture()
def codex_home(tmp_path: Path) -> Path:
    return tmp_path / "home"


class TestDoctorFix:
    def test_doctor_fix_repairs_partial_codex_hooks(
        self,
        project_root: Path,
        codex_home: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(project_root)
        monkeypatch.setenv("HOME", str(codex_home))

        assert main(["install", "codex"]) == 0
        hooks_path = project_root / ".codex" / "hooks.json"
        document = json.loads(hooks_path.read_text(encoding="utf-8"))
        stop_groups = document["hooks"]["Stop"]
        stop_groups[0]["hooks"] = [
            hook
            for hook in stop_groups[0]["hooks"]
            if hook.get("hmArch", {}).get("role") == "record"
        ]
        hooks_path.write_text(json.dumps(document), encoding="utf-8")

        assert main(["doctor", "codex"]) == 1

        assert main(["doctor", "codex", "--fix"]) == 0
        err = capsys.readouterr().err
        assert "Applied" in err or "Re-installed" in err

        fixed = json.loads(hooks_path.read_text(encoding="utf-8"))
        roles = {
            hook.get("hmArch", {}).get("role")
            for group in fixed["hooks"]["Stop"]
            for hook in group["hooks"]
            if hook.get("hmArch")
        }
        assert "record" in roles
        assert "consolidate" in roles

    def test_apply_safe_fixes_skips_hermes(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        hermes_home = tmp_path / "hermes"
        hermes_home.mkdir()
        (hermes_home / "config.yaml").write_text(
            "memory:\n  provider: mem0\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("HERMES_HOME", str(hermes_home))

        report = apply_safe_fixes(agent="hermes", global_install=False)
        assert report.applied_count == 0


class TestStorageDiagnostics:
    def test_storage_diagnostics_report_permission_denied(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_dir = tmp_path / "locked"
        db_dir.mkdir()
        db_path = db_dir / "memory.db"
        _seed_memory(db_path)
        os.chmod(db_dir, 0o555)

        monkeypatch.setenv("HM_ARCH_PROJECT_DB_PATH", str(db_path))
        try:
            diagnostics = storage_diagnostics()
        finally:
            os.chmod(db_dir, 0o755)

        codes = {item.code for item in diagnostics}
        assert "storage.project.permission_denied" in codes

    def test_doctor_includes_storage_diagnostics(
        self,
        project_root: Path,
        codex_home: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(project_root)
        monkeypatch.setenv("HOME", str(codex_home))

        main(["doctor", "codex"])
        err = capsys.readouterr().err
        assert "storage: diagnostics" in err


class TestBackupRestoreRepair:
    def test_backup_restore_round_trip_preserves_memories(self, tmp_path: Path) -> None:
        source_db = tmp_path / "source.db"
        memory_id = _seed_memory(source_db)
        backup_dir = tmp_path / "backup"
        target_db = tmp_path / "restored.db"

        report = backup_database(
            source_db,
            backup_dir,
            storage_scope=StorageScope.PROJECT,
        )
        assert report.memory_row_count >= 1
        assert (backup_dir / "manifest.json").exists()

        restore_report = restore_database(backup_dir, target_db, confirm=True)
        assert restore_report.replaced_existing is False

        with HMArch(config=MemoryConfig(db_path=str(target_db))) as memory:
            result = memory.search("Recovery workflow", min_retention=0.0)

        assert any(item.memory_id == memory_id for item in result.results)

    def test_failed_restore_preserves_existing_target(self, tmp_path: Path) -> None:
        source_db = tmp_path / "source.db"
        target_db = tmp_path / "target.db"
        backup_dir = tmp_path / "backup"

        with HMArch(config=MemoryConfig(db_path=str(source_db))) as memory:
            memory.add(
                "SOURCE MEMORY SHOULD NOT MATTER",
                event_type=EventType.OBSERVATION,
            )
        with HMArch(config=MemoryConfig(db_path=str(target_db))) as memory:
            memory.add(
                "TARGET MEMORY MUST SURVIVE FAILED RESTORE",
                event_type=EventType.OBSERVATION,
            )

        backup_database(source_db, backup_dir, storage_scope=StorageScope.PROJECT)

        manifest_path = backup_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"].append("source.db-wal")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with pytest.raises(DatabaseRecoveryError, match="backup file missing"):
            restore_database(backup_dir, target_db, confirm=True)

        assert target_db.exists()
        with sqlite3.connect(target_db) as conn:
            rows = conn.execute("SELECT content FROM episodes").fetchall()
        assert any("TARGET MEMORY MUST SURVIVE FAILED RESTORE" in row[0] for row in rows)

    def test_restore_requires_confirm(self, tmp_path: Path) -> None:
        source_db = tmp_path / "source.db"
        _seed_memory(source_db)
        backup_dir = tmp_path / "backup"
        backup_database(source_db, backup_dir, storage_scope=StorageScope.PROJECT)

        with pytest.raises(DatabaseRecoveryError, match="--confirm"):
            restore_database(backup_dir, tmp_path / "target.db", confirm=False)

    def test_repair_restores_missing_tables(self, tmp_path: Path) -> None:
        import sqlite3

        db_path = tmp_path / "broken.db"
        _seed_memory(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.execute("DROP TABLE episodes")
            conn.commit()

        report = repair_database(db_path)
        assert report.integrity_ok

        with SQLiteStore(db_path) as store:
            tables = {
                row["name"]
                for row in store.query(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        assert "episodes" in tables

    def test_cli_backup_restore_workflow(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        source_db = tmp_path / "cli-source.db"
        _seed_memory(source_db)
        backup_dir = tmp_path / "cli-backup"
        target_db = tmp_path / "cli-target.db"

        monkeypatch.setenv("HM_ARCH_PROJECT_DB_PATH", str(source_db))

        assert main(["memory", "backup", "-o", str(backup_dir)]) == 0

        monkeypatch.setenv("HM_ARCH_PROJECT_DB_PATH", str(target_db))
        assert (
            main(
                [
                    "memory",
                    "restore",
                    str(backup_dir),
                    "--target-scope",
                    "project",
                    "--confirm",
                ]
            )
            == 0
        )

        with HMArch(config=MemoryConfig(db_path=str(target_db))) as memory:
            result = memory.search("Recovery workflow", min_retention=0.0)
        assert result.results

    def test_cli_repair_reports_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        db_path = tmp_path / "repair.db"
        _seed_memory(db_path)
        monkeypatch.setenv("HM_ARCH_PROJECT_DB_PATH", str(db_path))

        assert main(["memory", "repair", "--scope", "project"]) == 0

    def test_doctor_json_logging(
        self,
        project_root: Path,
        codex_home: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(project_root)
        monkeypatch.setenv("HOME", str(codex_home))

        main(["doctor", "codex", "--json"])
        err = capsys.readouterr().err
        json_lines = [
            line
            for line in err.splitlines()
            if line.startswith("{") and '"phase"' in line
        ]
        assert json_lines
        payload = json.loads(json_lines[0])
        assert payload["phase"] == "doctor"
