"""Offline tests for Codex integration installer (MEM-44)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from hm_arch.integrations.cli.main import main
from hm_arch.integrations.codex.installer import (
    InstallScope,
    install_codex,
    merge_hm_arch_hooks,
    remove_hm_arch_hooks,
    uninstall_codex,
)
from hm_arch.integrations.codex.manifest import (
    HM_ARCH_META_KEY,
    HM_ARCH_OWNER,
    is_hm_arch_hook,
    resolve_hm_arch_codex_command,
)


@pytest.fixture()
def codex_home(tmp_path: Path) -> Path:
    return tmp_path / "home"


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


def _user_hook(command: str = "echo user-hook") -> dict:
    return {"type": "command", "command": command, "statusMessage": "user"}


def _load_hooks(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _hm_arch_hooks(document: dict) -> list[dict]:
    found: list[dict] = []
    for groups in document.get("hooks", {}).values():
        for group in groups:
            for hook in group.get("hooks", []):
                if is_hm_arch_hook(hook):
                    found.append(hook)
    return found


def test_merge_preserves_existing_user_hooks(
    project_root: Path,
    codex_home: Path,
) -> None:
    hooks_path = project_root / ".codex" / "hooks.json"
    hooks_path.parent.mkdir(parents=True)
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                _user_hook("echo keep-me"),
                            ]
                        }
                    ],
                    "Stop": [
                        {
                            "hooks": [
                                _user_hook("echo stop-user"),
                            ]
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    install_codex(
        InstallScope.PROJECT,
        project_root=project_root,
        home=codex_home,
    )
    document = _load_hooks(hooks_path)

    user_commands = [
        hook["command"]
        for groups in document["hooks"].values()
        for group in groups
        for hook in group["hooks"]
        if not is_hm_arch_hook(hook)
    ]
    assert user_commands == ["echo keep-me", "echo stop-user"]
    assert len(_hm_arch_hooks(document)) == 3


def test_repeat_install_is_idempotent(project_root: Path, codex_home: Path) -> None:
    first = install_codex(
        InstallScope.PROJECT,
        project_root=project_root,
        home=codex_home,
    )
    before = _load_hooks(first.paths.hooks_json)
    second = install_codex(
        InstallScope.PROJECT,
        project_root=project_root,
        home=codex_home,
    )
    after = _load_hooks(second.paths.hooks_json)

    assert before == after
    assert second.hooks_json_changed is False
    assert len(_hm_arch_hooks(after)) == 3


def test_uninstall_preserves_top_level_fields_when_hooks_empty(
    project_root: Path,
    codex_home: Path,
) -> None:
    hooks_path = project_root / ".codex" / "hooks.json"
    hooks_path.parent.mkdir(parents=True)
    hooks_path.write_text(
        json.dumps({"version": 1, "notes": "keep me", "hooks": {}}),
        encoding="utf-8",
    )

    install_codex(
        InstallScope.PROJECT,
        project_root=project_root,
        home=codex_home,
    )
    uninstall_codex(
        InstallScope.PROJECT,
        project_root=project_root,
        home=codex_home,
    )

    assert hooks_path.exists()
    assert _load_hooks(hooks_path) == {"version": 1, "notes": "keep me"}


def test_uninstall_preserves_user_hooks(project_root: Path, codex_home: Path) -> None:
    hooks_path = project_root / ".codex" / "hooks.json"
    hooks_path.parent.mkdir(parents=True)
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [{"hooks": [_user_hook("echo keep-me")]}],
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [_user_hook("echo pretool")],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    install_codex(
        InstallScope.PROJECT,
        project_root=project_root,
        home=codex_home,
    )

    uninstall_codex(
        InstallScope.PROJECT,
        project_root=project_root,
        home=codex_home,
    )

    remaining = _load_hooks(hooks_path)
    assert _hm_arch_hooks(remaining) == []
    user_commands = [
        hook["command"]
        for groups in remaining["hooks"].values()
        for group in groups
        for hook in group["hooks"]
    ]
    assert user_commands == ["echo keep-me", "echo pretool"]


def test_install_enables_required_hook_settings(
    project_root: Path,
    codex_home: Path,
) -> None:
    config_path = project_root / ".codex" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("[model]\nname = \"test\"\n", encoding="utf-8")

    result = install_codex(
        InstallScope.PROJECT,
        project_root=project_root,
        home=codex_home,
    )

    text = config_path.read_text(encoding="utf-8")
    assert "hooks = true" in text or "codex_hooks = true" in text
    assert result.config_toml_changed is True
    assert 'name = "test"' in text


def test_install_does_not_disable_existing_hooks_flag(
    project_root: Path,
    codex_home: Path,
) -> None:
    config_path = project_root / ".codex" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("[features]\ncodex_hooks = true\n", encoding="utf-8")

    result = install_codex(
        InstallScope.PROJECT,
        project_root=project_root,
        home=codex_home,
    )

    assert result.config_toml_changed is False
    assert config_path.read_text(encoding="utf-8") == "[features]\ncodex_hooks = true\n"


def test_global_install_uses_home_codex_dir(
    project_root: Path,
    codex_home: Path,
) -> None:
    result = install_codex(
        InstallScope.GLOBAL,
        project_root=project_root,
        home=codex_home,
    )

    assert result.paths.root == codex_home / ".codex"
    assert result.paths.hooks_json.exists()


def test_merge_and_remove_helpers_round_trip() -> None:
    document = {
        "hooks": {
            "UserPromptSubmit": [{"hooks": [_user_hook()]}],
        }
    }
    merged = merge_hm_arch_hooks(json.loads(json.dumps(document)))
    assert len(_hm_arch_hooks(merged)) == 3

    cleaned = remove_hm_arch_hooks(merged)
    assert _hm_arch_hooks(cleaned) == []
    assert cleaned["hooks"]["UserPromptSubmit"][0]["hooks"] == [_user_hook()]


def test_installed_hooks_carry_owner_metadata(
    project_root: Path,
    codex_home: Path,
) -> None:
    install_codex(
        InstallScope.PROJECT,
        project_root=project_root,
        home=codex_home,
    )
    document = _load_hooks(project_root / ".codex" / "hooks.json")
    for hook in _hm_arch_hooks(document):
        meta = hook[HM_ARCH_META_KEY]
        assert meta["owner"] == HM_ARCH_OWNER
        assert meta["role"] in {"recall", "record", "consolidate"}


def test_hook_command_uses_standalone_executable_without_python_module_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "hm_arch.integrations.executable.shutil.which",
        lambda name: None,
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/tmp/hm-arch")

    assert resolve_hm_arch_codex_command("recall") == "/tmp/hm-arch codex recall"


def test_cli_install_and_uninstall_subcommands(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(project_root)
    assert main(["install", "codex"]) == 0
    hooks_path = project_root / ".codex" / "hooks.json"
    assert hooks_path.exists()
    assert len(_hm_arch_hooks(_load_hooks(hooks_path))) == 3

    assert main(["uninstall", "codex"]) == 0
    assert not hooks_path.exists()


def test_codex_bridge_recall_subcommand_emits_context(
    hook_db_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hm_arch import EventType, HMArch, MemoryConfig

    config = MemoryConfig(db_path=hook_db_path, replay_sample_ratio=1.0)
    with HMArch(config=config) as memory:
        memory.add(
            "Repository uses pytest for offline verification",
            event_type=EventType.OBSERVATION,
            importance=0.85,
        )

    monkeypatch.setenv("HM_ARCH_DB_PATH", hook_db_path)
    proc = subprocess.run(
        [sys.executable, "-m", "hm_arch.integrations.cli", "codex", "recall"],
        input=json.dumps({"prompt": "offline pytest"}),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(proc.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert "pytest" in context.lower() or "offline" in context.lower()


@pytest.fixture()
def hook_db_path() -> str:
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        yield str(Path(tmpdir) / "codex_installer.db")
