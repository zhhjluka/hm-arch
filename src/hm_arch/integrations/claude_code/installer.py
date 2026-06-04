"""Install and uninstall HM-Arch hooks in Claude Code configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .manifest import (
    HOOK_ROLES,
    IDLE_EVENT,
    RECALL_EVENT,
    STOP_EVENT,
    build_hook_definition,
    is_hm_arch_hook,
    roles_for_event,
)


class InstallScope(str, Enum):
    """Whether Claude Code configuration is project-local or user-global."""

    PROJECT = "project"
    GLOBAL = "global"


@dataclass(frozen=True)
class ClaudeCodeInstallPaths:
    """Resolved Claude Code configuration paths for one install scope."""

    root: Path
    settings_json: Path


@dataclass
class InstallResult:
    """Summary of a Claude Code install or uninstall operation."""

    scope: InstallScope
    paths: ClaudeCodeInstallPaths
    settings_json_changed: bool
    installed_roles: tuple[str, ...] = ()


def resolve_claude_code_paths(
    scope: InstallScope,
    *,
    project_root: Path | None = None,
    home: Path | None = None,
) -> ClaudeCodeInstallPaths:
    """Resolve Claude Code config file locations for *scope*."""
    if scope is InstallScope.GLOBAL:
        root = (home or Path.home()) / ".claude"
    else:
        root = (project_root or Path.cwd()) / ".claude"
    return ClaudeCodeInstallPaths(
        root=root,
        settings_json=root / "settings.json",
    )


def _load_settings_document(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"{path} hooks field must be an object")
    return data


def _default_matcher_group(event: str) -> dict[str, Any]:
    group: dict[str, Any] = {"hooks": []}
    if event not in {RECALL_EVENT, STOP_EVENT, IDLE_EVENT}:
        group["matcher"] = "*"
    return group


def _select_matcher_group(groups: list[Any], event: str) -> dict[str, Any]:
    for entry in groups:
        if not isinstance(entry, dict):
            continue
        matcher = entry.get("matcher")
        if matcher in (None, "", "*"):
            hooks = entry.setdefault("hooks", [])
            if isinstance(hooks, list):
                return entry
    group = _default_matcher_group(event)
    groups.append(group)
    return group


def _strip_hm_arch_hooks(hooks: list[Any]) -> list[Any]:
    kept: list[Any] = []
    for hook in hooks:
        if isinstance(hook, dict) and is_hm_arch_hook(hook):
            continue
        kept.append(hook)
    return kept


def _merge_event_hooks(
    hooks_root: dict[str, Any],
    event: str,
    roles: tuple[str, ...],
) -> None:
    groups = hooks_root.setdefault(event, [])
    if not isinstance(groups, list):
        raise ValueError(f"hooks.{event} must be an array")

    group = _select_matcher_group(groups, event)
    hook_list = group.setdefault("hooks", [])
    if not isinstance(hook_list, list):
        raise ValueError(f"hooks.{event} matcher group hooks must be an array")

    preserved = _strip_hm_arch_hooks(hook_list)
    installed = [build_hook_definition(role) for role in roles]
    group["hooks"] = [*preserved, *installed]


def _prune_empty_groups(hooks_root: dict[str, Any]) -> None:
    for event, groups in list(hooks_root.items()):
        if not isinstance(groups, list):
            continue
        kept_groups: list[Any] = []
        for group in groups:
            if not isinstance(group, dict):
                kept_groups.append(group)
                continue
            hook_list = group.get("hooks", [])
            if isinstance(hook_list, list) and hook_list:
                kept_groups.append(group)
        if kept_groups:
            hooks_root[event] = kept_groups
        else:
            del hooks_root[event]


def merge_hm_arch_hooks(document: dict[str, Any]) -> dict[str, Any]:
    """Merge HM-Arch hooks into an existing Claude Code ``settings.json`` document."""
    hooks_root = document.setdefault("hooks", {})
    if not isinstance(hooks_root, dict):
        raise ValueError("hooks field must be an object")

    for event in (RECALL_EVENT, STOP_EVENT, IDLE_EVENT):
        roles = roles_for_event(event)
        if roles:
            _merge_event_hooks(hooks_root, event, roles)

    return document


def remove_hm_arch_hooks(document: dict[str, Any]) -> dict[str, Any]:
    """Remove only HM-Arch-owned hooks from a Claude Code ``settings.json`` document."""
    hooks_root = document.get("hooks")
    if not isinstance(hooks_root, dict):
        return document

    for event, groups in list(hooks_root.items()):
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            hook_list = group.get("hooks")
            if not isinstance(hook_list, list):
                continue
            group["hooks"] = _strip_hm_arch_hooks(hook_list)

    _prune_empty_groups(hooks_root)
    if not hooks_root:
        document.pop("hooks", None)
    return document


def _should_delete_settings_file(document: dict[str, Any]) -> bool:
    """Return True when ``settings.json`` has no user-owned content left."""
    return not document


def _write_settings_json(path: Path, document: dict[str, Any]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(document, indent=2, ensure_ascii=False)
    serialized = f"{serialized}\n"
    if path.exists() and path.read_text(encoding="utf-8") == serialized:
        return False
    path.write_text(serialized, encoding="utf-8")
    return True


def install_claude_code(
    scope: InstallScope = InstallScope.PROJECT,
    *,
    project_root: Path | None = None,
    home: Path | None = None,
) -> InstallResult:
    """Install HM-Arch Claude Code hooks for *scope* (idempotent)."""
    paths = resolve_claude_code_paths(
        scope,
        project_root=project_root,
        home=home,
    )
    document = _load_settings_document(paths.settings_json)
    merge_hm_arch_hooks(document)
    settings_changed = _write_settings_json(paths.settings_json, document)
    return InstallResult(
        scope=scope,
        paths=paths,
        settings_json_changed=settings_changed,
        installed_roles=HOOK_ROLES,
    )


def uninstall_claude_code(
    scope: InstallScope = InstallScope.PROJECT,
    *,
    project_root: Path | None = None,
    home: Path | None = None,
) -> InstallResult:
    """Remove HM-Arch-owned Claude Code hooks for *scope*."""
    paths = resolve_claude_code_paths(
        scope,
        project_root=project_root,
        home=home,
    )
    if not paths.settings_json.exists():
        return InstallResult(
            scope=scope,
            paths=paths,
            settings_json_changed=False,
            installed_roles=(),
        )

    document = _load_settings_document(paths.settings_json)
    remove_hm_arch_hooks(document)
    if _should_delete_settings_file(document):
        paths.settings_json.unlink(missing_ok=True)
        settings_changed = True
    else:
        settings_changed = _write_settings_json(paths.settings_json, document)

    return InstallResult(
        scope=scope,
        paths=paths,
        settings_json_changed=settings_changed,
        installed_roles=(),
    )
