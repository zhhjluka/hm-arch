"""Offline tests for OpenClaw integration management CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hm_arch.integrations.cli.main import main
from hm_arch.integrations.openclaw.config import (
    HM_ARCH_PLUGIN_ID,
    load_openclaw_config,
    read_memory_slot,
    resolve_openclaw_config_path,
)


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


@pytest.fixture()
def openclaw_home(tmp_path: Path) -> Path:
    return tmp_path / "home"


def _configure_openclaw_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    home: Path,
    project_root: Path | None = None,
    global_install: bool = False,
    config_path: Path | None = None,
) -> Path:
    monkeypatch.setenv("HOME", str(home))
    state_dir = home / ".openclaw"
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(state_dir))
    if config_path is not None:
        monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(config_path))
        if project_root is not None:
            monkeypatch.chdir(project_root)
        return config_path
    if project_root is not None:
        monkeypatch.chdir(project_root)
    if global_install:
        return state_dir / "openclaw.json"
    project_config = (project_root or Path.cwd()) / ".openclaw" / "openclaw.json"
    return project_config


def test_install_status_doctor_openclaw_lifecycle(
    project_root: Path,
    openclaw_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = _configure_openclaw_env(
        monkeypatch,
        home=openclaw_home,
        project_root=project_root,
    )

    assert main(["install", "openclaw"]) == 0
    err = capsys.readouterr().err
    assert "openclaw (project): partial" in err
    assert "Configured OpenClaw memory slot" in err
    assert "Installed HM-Arch OpenClaw plugin" in err
    assert "management-stage stub" in err
    assert config_path.exists()
    assert (config_path.parent / "extensions" / HM_ARCH_PLUGIN_ID / "openclaw.plugin.json").exists()

    config = load_openclaw_config(config_path)
    assert read_memory_slot(config) == HM_ARCH_PLUGIN_ID
    assert config["plugins"]["entries"][HM_ARCH_PLUGIN_ID]["enabled"] is True

    assert main(["status", "openclaw"]) == 0
    err = capsys.readouterr().err
    assert "openclaw (project): partial" in err
    assert "plugins.slots.memory is set to 'memory-hm-arch'" in err
    assert "management-stage stub" in err

    assert main(["doctor", "openclaw"]) == 1
    err = capsys.readouterr().err
    assert (
        "HM-Arch database schema is initialized" in err
        or "Created HM-Arch database" in err
        or "HM-Arch database exists at" in err
    )

    assert main(["uninstall", "openclaw"]) == 0
    err = capsys.readouterr().err
    assert "openclaw (project): not_installed" in err
    assert "Removed HM-Arch OpenClaw config" in err
    assert "Removed HM-Arch OpenClaw plugin" in err
    assert not (config_path.parent / "extensions" / HM_ARCH_PLUGIN_ID).exists()

    config = load_openclaw_config(config_path)
    assert read_memory_slot(config) == "none"
    assert HM_ARCH_PLUGIN_ID not in config.get("plugins", {}).get("entries", {})


def test_install_openclaw_global_scope(
    openclaw_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _configure_openclaw_env(
        monkeypatch,
        home=openclaw_home,
        global_install=True,
    )

    assert main(["install", "openclaw", "--global"]) == 0
    assert config_path.exists()
    config = load_openclaw_config(config_path)
    assert read_memory_slot(config) == HM_ARCH_PLUGIN_ID


def test_status_openclaw_reports_memory_slot_conflict(
    project_root: Path,
    openclaw_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = _configure_openclaw_env(
        monkeypatch,
        home=openclaw_home,
        project_root=project_root,
    )
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "plugins": {
                    "slots": {"memory": "memory-lancedb"},
                    "entries": {
                        "memory-lancedb": {"enabled": True, "config": {}},
                    },
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    assert main(["status", "openclaw"]) == 1
    err = capsys.readouterr().err
    assert "conflict" in err.lower() or "memory-lancedb" in err

    assert main(["doctor", "openclaw"]) == 1
    err = capsys.readouterr().err
    assert "conflict" in err.lower() or "memory-lancedb" in err

    assert main(["install", "openclaw"]) == 2
    err = capsys.readouterr().err
    assert "conflict" in err.lower() or "memory-lancedb" in err


def test_uninstall_openclaw_preserves_unrelated_memory_slot(
    project_root: Path,
    openclaw_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = _configure_openclaw_env(
        monkeypatch,
        home=openclaw_home,
        project_root=project_root,
    )
    extension_dir = config_path.parent / "extensions" / HM_ARCH_PLUGIN_ID
    extension_dir.mkdir(parents=True)
    (extension_dir / "openclaw.plugin.json").write_text("{}", encoding="utf-8")
    custom_db = config_path.parent / "custom.db"
    custom_db.write_text("placeholder", encoding="utf-8")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "plugins": {
                    "slots": {"memory": "memory-mem0"},
                    "entries": {
                        HM_ARCH_PLUGIN_ID: {
                            "enabled": True,
                            "config": {"dbPath": "custom.db"},
                        },
                        "memory-mem0": {"enabled": True, "config": {}},
                    },
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    assert main(["uninstall", "openclaw"]) == 0
    err = capsys.readouterr().err
    assert "Removed HM-Arch OpenClaw config" in err
    assert "Removed HM-Arch OpenClaw plugin" in err
    assert "Preserved HM-Arch database" in err
    assert custom_db.exists()
    assert not extension_dir.exists()

    config = load_openclaw_config(config_path)
    assert read_memory_slot(config) == "memory-mem0"
    assert HM_ARCH_PLUGIN_ID not in config["plugins"]["entries"]
    assert "memory-mem0" in config["plugins"]["entries"]


def test_install_status_doctor_openclaw_custom_config_path_lifecycle(
    project_root: Path,
    openclaw_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    custom_config = openclaw_home / "custom" / "custom.json"
    custom_db = custom_config.parent / "custom-memory.db"
    config_path = _configure_openclaw_env(
        monkeypatch,
        home=openclaw_home,
        project_root=project_root,
        config_path=custom_config,
    )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "plugins": {
                    "entries": {
                        HM_ARCH_PLUGIN_ID: {
                            "enabled": True,
                            "config": {"dbPath": "custom-memory.db"},
                        }
                    }
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    assert main(["install", "openclaw"]) == 0
    err = capsys.readouterr().err
    assert "openclaw (project): partial" in err
    assert config_path.exists()
    assert not (config_path.parent / "hm_arch_memory.db").exists()

    assert main(["doctor", "openclaw"]) == 1
    err = capsys.readouterr().err
    assert (
        f"HM-Arch database schema is initialized at {custom_db}" in err
        or f"Created HM-Arch database at {custom_db}" in err
        or f"HM-Arch database exists at {custom_db}" in err
    )
    assert custom_db.exists()

    assert main(["status", "openclaw"]) == 0
    err = capsys.readouterr().err
    assert f"HM-Arch database exists at {custom_db}" in err


def test_install_openclaw_config_write_permission_error(
    project_root: Path,
    openclaw_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    readonly_dir = openclaw_home / "readonly"
    readonly_dir.mkdir(parents=True)
    readonly_dir.chmod(0o555)
    config_path = readonly_dir / "openclaw.json"
    _configure_openclaw_env(
        monkeypatch,
        home=openclaw_home,
        project_root=project_root,
        config_path=config_path,
    )

    assert main(["install", "openclaw"]) == 2
    err = capsys.readouterr().err
    assert "openclaw (project): partial" in err
    assert "Could not write OpenClaw config" in err
    assert not config_path.exists()


def test_install_openclaw_extension_write_permission_error(
    project_root: Path,
    openclaw_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = _configure_openclaw_env(
        monkeypatch,
        home=openclaw_home,
        project_root=project_root,
    )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    (config_path.parent / "extensions").write_text("blocked", encoding="utf-8")

    assert main(["install", "openclaw"]) == 2
    err = capsys.readouterr().err
    assert "openclaw (project): partial" in err
    assert "Could not write HM-Arch OpenClaw plugin" in err
    assert config_path.exists()


def test_resolve_openclaw_config_path_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    custom = tmp_path / "custom-openclaw.json"
    monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(custom))
    assert resolve_openclaw_config_path(global_install=False) == custom
    assert resolve_openclaw_config_path(global_install=True) == custom
