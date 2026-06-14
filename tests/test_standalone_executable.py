"""Smoke tests for the PyInstaller standalone ``hm-arch`` executable (MEM-61)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from hm_arch import EventType, HMArch, MemoryConfig

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BUILD_SCRIPT = _REPO_ROOT / "scripts" / "build_standalone.py"
_DEFAULT_EXECUTABLE = _REPO_ROOT / "dist" / "standalone" / (
    "hm-arch.exe" if sys.platform == "win32" else "hm-arch"
)


def _build_standalone_executable() -> Path:
    subprocess.run(
        [sys.executable, str(_BUILD_SCRIPT), "--clean"],
        check=True,
        cwd=_REPO_ROOT,
    )
    if not _DEFAULT_EXECUTABLE.is_file():
        raise FileNotFoundError(f"Expected executable at {_DEFAULT_EXECUTABLE}")
    return _DEFAULT_EXECUTABLE


@pytest.fixture(scope="session")
def standalone_executable() -> Path:
    """Build (or reuse) the standalone executable once per test session."""
    return _build_standalone_executable()


@pytest.fixture()
def cli_db_path() -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield str(Path(tmpdir) / "standalone_cli.db")


@pytest.fixture()
def cli_env(cli_db_path: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setenv("HM_ARCH_DB_PATH", cli_db_path)
    return {"HM_ARCH_DB_PATH": cli_db_path}


def _seed_memory(db_path: str) -> None:
    config = MemoryConfig(db_path=db_path, replay_sample_ratio=1.0)
    with HMArch(config=config) as memory:
        memory.add(
            "Repository uses uv and pytest for offline verification",
            event_type=EventType.OBSERVATION,
            importance=0.85,
        )


def _run_executable(
    executable: Path,
    args: list[str],
    *,
    env: dict[str, str],
    stdin: str | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(executable), *args],
        input=stdin,
        text=True,
        capture_output=True,
        cwd=cwd or _REPO_ROOT,
        env={**os.environ, **env},
    )


def test_standalone_executable_help(standalone_executable: Path) -> None:
    proc = _run_executable(standalone_executable, ["--help"], env={})
    assert proc.returncode == 0
    assert "recall" in proc.stdout
    assert "install" in proc.stdout


def test_standalone_recall_record_consolidate(
    standalone_executable: Path,
    cli_db_path: str,
    cli_env: dict[str, str],
) -> None:
    _seed_memory(cli_db_path)

    recall = _run_executable(
        standalone_executable,
        ["recall"],
        env=cli_env,
        stdin=json.dumps({"task": "offline pytest"}),
    )
    assert recall.returncode == 0, recall.stderr
    recall_payload = json.loads(recall.stdout)
    assert recall_payload["ok"] is True
    assert recall_payload["result_count"] >= 1

    record = _run_executable(
        standalone_executable,
        ["record"],
        env=cli_env,
        stdin=json.dumps(
            {"user_message": "What stack do we use?", "agent_message": "uv run pytest."}
        ),
    )
    assert record.returncode == 0, record.stderr
    record_payload = json.loads(record.stdout)
    assert record_payload["ok"] is True
    assert record_payload["recorded_count"] == 2

    consolidate = _run_executable(
        standalone_executable,
        ["consolidate"],
        env=cli_env,
        stdin=json.dumps({}),
    )
    assert consolidate.returncode == 0, consolidate.stderr
    consolidate_payload = json.loads(consolidate.stdout)
    assert consolidate_payload["ok"] is True


def test_standalone_integration_management_lifecycle(
    standalone_executable: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.chdir(project_root)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    assert (
        _run_executable(
            standalone_executable,
            ["install", "codex"],
            env={},
            cwd=project_root,
        ).returncode
        == 0
    )
    hooks_path = project_root / ".codex" / "hooks.json"
    assert hooks_path.is_file()

    status = _run_executable(
        standalone_executable,
        ["status", "codex"],
        env={},
        cwd=project_root,
    )
    assert status.returncode == 0
    status_output = f"{status.stdout}\n{status.stderr}".lower()
    assert "installed" in status_output

    doctor = _run_executable(
        standalone_executable,
        ["doctor", "codex"],
        env={},
        cwd=project_root,
    )
    assert doctor.returncode == 0

    uninstall = _run_executable(
        standalone_executable,
        ["uninstall", "codex"],
        env={},
        cwd=project_root,
    )
    assert uninstall.returncode == 0
    assert not hooks_path.exists()


def test_standalone_claude_code_integration_lifecycle(
    standalone_executable: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "claude_project"
    project_root.mkdir()
    monkeypatch.chdir(project_root)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    assert (
        _run_executable(
            standalone_executable,
            ["install", "claude-code"],
            env={},
            cwd=project_root,
        ).returncode
        == 0
    )
    settings_path = project_root / ".claude" / "settings.json"
    assert settings_path.is_file()

    status = _run_executable(
        standalone_executable,
        ["status", "claude-code"],
        env={},
        cwd=project_root,
    )
    assert status.returncode == 0

    doctor = _run_executable(
        standalone_executable,
        ["doctor", "claude-code"],
        env={},
        cwd=project_root,
    )
    assert doctor.returncode == 0

    uninstall = _run_executable(
        standalone_executable,
        ["uninstall", "claude-code"],
        env={},
        cwd=project_root,
    )
    assert uninstall.returncode == 0
    assert not settings_path.exists()


def test_standalone_hermes_management_without_python_on_path(
    standalone_executable: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir()
    (hermes_home / "config.yaml").write_text(
        "memory:\n  provider: hm-arch\nplugins:\n  hm-arch:\n    db_path: test.db\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("HM_ARCH_HOME", str(home / ".hm-arch"))
    (home / ".hm-arch").mkdir()

    install = _run_executable(
        standalone_executable,
        ["install", "hermes"],
        env={},
    )
    assert install.returncode == 0
    assert (hermes_home / "plugins" / "hm-arch" / "__init__.py").exists()
    assert (hermes_home / "test.db").exists()

    status = _run_executable(
        standalone_executable,
        ["status", "hermes"],
        env={},
    )
    assert status.returncode == 0

    doctor = _run_executable(
        standalone_executable,
        ["doctor", "hermes"],
        env={},
    )
    assert doctor.returncode == 0

    uninstall = _run_executable(
        standalone_executable,
        ["uninstall", "hermes"],
        env={},
    )
    assert uninstall.returncode == 0, uninstall.stderr
    assert "hermes: not_installed" in uninstall.stderr
    assert "Removed HM-Arch Hermes config" in uninstall.stderr
    assert "Preserved HM-Arch database" in uninstall.stderr
    assert not (hermes_home / "plugins" / "hm-arch").exists()
    assert (hermes_home / "test.db").exists()


def test_standalone_executable_runs_without_python_on_path(
    standalone_executable: Path,
    cli_env: dict[str, str],
) -> None:
    """The frozen binary should not depend on a system ``python`` on PATH."""
    env = {**cli_env, "PATH": ""}
    proc = _run_executable(
        standalone_executable,
        ["recall"],
        env=env,
        stdin=json.dumps({"task": "path isolation"}),
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True


def test_standalone_matches_python_cli_recall(
    standalone_executable: Path,
    cli_db_path: str,
    cli_env: dict[str, str],
) -> None:
    _seed_memory(cli_db_path)
    payload = json.dumps({"task": "offline pytest"})

    python_proc = subprocess.run(
        [sys.executable, "-m", "hm_arch.integrations.cli", "recall"],
        input=payload,
        text=True,
        capture_output=True,
        check=True,
        cwd=_REPO_ROOT,
        env={**cli_env, "PATH": os.environ.get("PATH", "")},
    )
    standalone_proc = _run_executable(
        standalone_executable,
        ["recall"],
        env=cli_env,
        stdin=payload,
    )
    assert standalone_proc.returncode == 0, standalone_proc.stderr

    python_out = json.loads(python_proc.stdout)
    standalone_out = json.loads(standalone_proc.stdout)
    assert standalone_out["ok"] == python_out["ok"]
    assert standalone_out["result_count"] == python_out["result_count"]
