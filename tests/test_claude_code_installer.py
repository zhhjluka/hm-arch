"""Offline tests for Claude Code integration installer (MEM-45)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from hm_arch.integrations.cli.main import main
from hm_arch.integrations.claude_code.installer import (
    InstallScope,
    install_claude_code,
    merge_hm_arch_hooks,
    remove_hm_arch_hooks,
    uninstall_claude_code,
)
from hm_arch.integrations.claude_code.manifest import (
    HM_ARCH_META_KEY,
    HM_ARCH_OWNER,
    IDLE_EVENT,
    is_hm_arch_hook,
)


@pytest.fixture()
def claude_home(tmp_path: Path) -> Path:
    return tmp_path / "home"


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


def _user_hook(command: str = "echo user-hook") -> dict:
    return {"type": "command", "command": command, "statusMessage": "user"}


def _load_settings(path: Path) -> dict:
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
    claude_home: Path,
) -> None:
    settings_path = project_root / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Read"]},
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
                },
            }
        ),
        encoding="utf-8",
    )

    install_claude_code(
        InstallScope.PROJECT,
        project_root=project_root,
        home=claude_home,
    )
    document = _load_settings(settings_path)

    assert document["permissions"] == {"allow": ["Read"]}
    user_commands = [
        hook["command"]
        for groups in document["hooks"].values()
        for group in groups
        for hook in group["hooks"]
        if not is_hm_arch_hook(hook)
    ]
    assert user_commands == ["echo keep-me", "echo stop-user"]
    assert len(_hm_arch_hooks(document)) == 3


def test_repeat_install_is_idempotent(project_root: Path, claude_home: Path) -> None:
    first = install_claude_code(
        InstallScope.PROJECT,
        project_root=project_root,
        home=claude_home,
    )
    before = _load_settings(first.paths.settings_json)
    second = install_claude_code(
        InstallScope.PROJECT,
        project_root=project_root,
        home=claude_home,
    )
    after = _load_settings(second.paths.settings_json)

    assert before == after
    assert second.settings_json_changed is False
    assert len(_hm_arch_hooks(after)) == 3


def test_uninstall_preserves_top_level_fields_when_hooks_empty(
    project_root: Path,
    claude_home: Path,
) -> None:
    settings_path = project_root / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps({"version": 1, "notes": "keep me", "hooks": {}}),
        encoding="utf-8",
    )

    install_claude_code(
        InstallScope.PROJECT,
        project_root=project_root,
        home=claude_home,
    )
    uninstall_claude_code(
        InstallScope.PROJECT,
        project_root=project_root,
        home=claude_home,
    )

    assert settings_path.exists()
    assert _load_settings(settings_path) == {"version": 1, "notes": "keep me"}


def test_uninstall_preserves_user_hooks(project_root: Path, claude_home: Path) -> None:
    settings_path = project_root / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
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
    install_claude_code(
        InstallScope.PROJECT,
        project_root=project_root,
        home=claude_home,
    )

    uninstall_claude_code(
        InstallScope.PROJECT,
        project_root=project_root,
        home=claude_home,
    )

    remaining = _load_settings(settings_path)
    assert _hm_arch_hooks(remaining) == []
    user_commands = [
        hook["command"]
        for groups in remaining["hooks"].values()
        for group in groups
        for hook in group["hooks"]
    ]
    assert user_commands == ["echo keep-me", "echo pretool"]


def test_global_install_uses_home_claude_dir(
    project_root: Path,
    claude_home: Path,
) -> None:
    result = install_claude_code(
        InstallScope.GLOBAL,
        project_root=project_root,
        home=claude_home,
    )

    assert result.paths.root == claude_home / ".claude"
    assert result.paths.settings_json.exists()


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
    claude_home: Path,
) -> None:
    install_claude_code(
        InstallScope.PROJECT,
        project_root=project_root,
        home=claude_home,
    )
    document = _load_settings(project_root / ".claude" / "settings.json")
    for hook in _hm_arch_hooks(document):
        meta = hook[HM_ARCH_META_KEY]
        assert meta["owner"] == HM_ARCH_OWNER
        assert meta["role"] in {"recall", "record", "consolidate"}


def test_consolidate_hook_targets_teammate_idle(
    project_root: Path,
    claude_home: Path,
) -> None:
    install_claude_code(
        InstallScope.PROJECT,
        project_root=project_root,
        home=claude_home,
    )
    document = _load_settings(project_root / ".claude" / "settings.json")
    idle_hooks = document["hooks"][IDLE_EVENT][0]["hooks"]
    consolidate = [hook for hook in idle_hooks if is_hm_arch_hook(hook)]
    assert len(consolidate) == 1
    assert consolidate[0][HM_ARCH_META_KEY]["role"] == "consolidate"


def test_merge_uses_default_matcher_group_for_new_events() -> None:
    document: dict = {"hooks": {}}
    merged = merge_hm_arch_hooks(document)
    recall_group = merged["hooks"]["UserPromptSubmit"][0]
    assert recall_group.get("matcher") in (None, "*", "")
    assert len(recall_group["hooks"]) == 1


def test_custom_matcher_groups_are_preserved(
    project_root: Path,
    claude_home: Path,
) -> None:
    settings_path = project_root / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [_user_hook("echo bash-only")],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    install_claude_code(
        InstallScope.PROJECT,
        project_root=project_root,
        home=claude_home,
    )
    document = _load_settings(settings_path)
    bash_group = document["hooks"]["PreToolUse"][0]
    assert bash_group["matcher"] == "Bash"
    assert bash_group["hooks"][0]["command"] == "echo bash-only"


def test_cli_install_and_uninstall_subcommands(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(project_root)
    assert main(["install", "claude-code"]) == 0
    settings_path = project_root / ".claude" / "settings.json"
    assert settings_path.exists()
    assert len(_hm_arch_hooks(_load_settings(settings_path))) == 3

    assert main(["uninstall", "claude-code"]) == 0
    assert not settings_path.exists()


def test_claude_code_bridge_recall_subcommand_emits_context(
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
        [sys.executable, "-m", "hm_arch.integrations.cli", "claude-code", "recall"],
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
        yield str(Path(tmpdir) / "claude_installer.db")
