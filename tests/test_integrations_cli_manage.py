"""Offline tests for hm-arch integration management CLI (MEM-47)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hm_arch.integrations.cli.main import main
from hm_arch.integrations.management.hermes import resolve_hermes_home
from hm_arch.integrations.management.hooks import inspect_codex_hooks


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


@pytest.fixture()
def codex_home(tmp_path: Path) -> Path:
    return tmp_path / "home"


def test_install_status_doctor_codex_lifecycle(
    project_root: Path,
    codex_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(project_root)
    monkeypatch.setenv("HOME", str(codex_home))

    assert main(["install", "codex"]) == 0
    hooks_path = project_root / ".codex" / "hooks.json"
    assert hooks_path.exists()
    assert len(inspect_codex_hooks(hooks_path)) == 3

    assert main(["status", "codex"]) == 0

    assert main(["doctor", "codex"]) == 0

    assert main(["uninstall", "codex"]) == 0
    assert not hooks_path.exists()


def test_doctor_codex_reports_not_installed(
    project_root: Path,
    codex_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(project_root)
    monkeypatch.setenv("HOME", str(codex_home))

    assert main(["doctor", "codex"]) == 1
    err = capsys.readouterr().err
    assert "not_installed" in err or "not installed" in err.lower()


def test_install_hermes_reports_unsupported_diagnostic(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["install", "hermes"]) == 2
    err = capsys.readouterr().err
    assert "hermes: unsupported" in err
    assert "hm-arch install hermes is not supported" in err
    assert "native plugin registration" in err
    assert "hm-arch status hermes" in err
    assert "hm-arch doctor hermes" in err


def test_status_hermes_reports_provider_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir()
    config_path = hermes_home / "config.yaml"
    config_path.write_text("memory:\n  provider: mem0\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    assert main(["status", "hermes"]) == 1
    err = capsys.readouterr().err
    assert "conflict" in err.lower() or "mem0" in err

    assert main(["doctor", "hermes"]) == 1
    err = capsys.readouterr().err
    assert "conflict" in err.lower() or "mem0" in err


def test_status_hermes_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hermes_home = tmp_path / "hermes_ok"
    hermes_home.mkdir()
    (hermes_home / "config.yaml").write_text(
        "memory:\n  provider: hm-arch\nplugins:\n  hm-arch:\n    db_path: test.db\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    assert main(["status", "hermes"]) == 0
    assert main(["doctor", "hermes"]) == 0


def test_uninstall_hermes_reports_unsupported_diagnostic(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["uninstall", "hermes"]) == 2
    err = capsys.readouterr().err
    assert "hermes: unsupported" in err
    assert "hm-arch uninstall hermes is not supported" in err
    assert "config.yaml" in err
    assert "without changing unrelated memory providers" in err


def test_status_all_agents(
    project_root: Path,
    codex_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(project_root)
    monkeypatch.setenv("HOME", str(codex_home))
    hermes_home = tmp_path / "hermes_all"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    assert main(["status"]) == 0


def test_cli_install_preserves_user_hooks_on_uninstall(
    project_root: Path,
    codex_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(project_root)
    monkeypatch.setenv("HOME", str(codex_home))

    hooks_path = project_root / ".codex" / "hooks.json"
    hooks_path.parent.mkdir(parents=True)
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "echo keep"}]}],
                }
            }
        ),
        encoding="utf-8",
    )

    assert main(["install", "codex"]) == 0
    document = json.loads(hooks_path.read_text(encoding="utf-8"))
    user_hooks = [
        hook
        for group in document["hooks"]["UserPromptSubmit"]
        for hook in group["hooks"]
        if hook.get("command") == "echo keep"
    ]
    assert user_hooks

    assert main(["uninstall", "codex"]) == 0
    document = json.loads(hooks_path.read_text(encoding="utf-8"))
    user_hooks = [
        hook
        for group in document["hooks"]["UserPromptSubmit"]
        for hook in group["hooks"]
        if hook.get("command") == "echo keep"
    ]
    assert user_hooks


def test_resolve_hermes_home_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    custom = tmp_path / "custom_hermes"
    monkeypatch.setenv("HERMES_HOME", str(custom))
    assert resolve_hermes_home() == custom
