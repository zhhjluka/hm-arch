"""Shared helpers for inspecting HM-Arch hook installations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from hm_arch.integrations.codex.manifest import HOOK_ROLES as CODEX_HOOK_ROLES
from hm_arch.integrations.codex.manifest import is_hm_arch_hook as is_codex_hm_arch_hook
from hm_arch.integrations.claude_code.manifest import (
    HOOK_ROLES as CLAUDE_HOOK_ROLES,
)
from hm_arch.integrations.claude_code.manifest import (
    is_hm_arch_hook as is_claude_hm_arch_hook,
)


def _collect_roles(
    document: dict[str, Any],
    *,
    is_owned_hook: Callable[[dict[str, Any]], bool],
) -> tuple[str, ...]:
    roles: set[str] = set()
    hooks_root = document.get("hooks")
    if not isinstance(hooks_root, dict):
        return ()

    for groups in hooks_root.values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            hook_list = group.get("hooks")
            if not isinstance(hook_list, list):
                continue
            for hook in hook_list:
                if not isinstance(hook, dict) or not is_owned_hook(hook):
                    continue
                meta = hook.get("hmArch")
                if isinstance(meta, dict):
                    role = meta.get("role")
                    if isinstance(role, str) and role:
                        roles.add(role)
    return tuple(sorted(roles))


def load_json_document(path: Path) -> dict[str, Any] | None:
    """Load a JSON config document when *path* exists."""
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def inspect_codex_hooks(path: Path) -> tuple[str, ...]:
    """Return installed HM-Arch Codex hook roles from *path*."""
    document = load_json_document(path)
    if document is None:
        return ()
    return _collect_roles(document, is_owned_hook=is_codex_hm_arch_hook)


def inspect_claude_hooks(path: Path) -> tuple[str, ...]:
    """Return installed HM-Arch Claude Code hook roles from *path*."""
    document = load_json_document(path)
    if document is None:
        return ()
    return _collect_roles(document, is_owned_hook=is_claude_hm_arch_hook)


def expected_codex_roles() -> tuple[str, ...]:
    return CODEX_HOOK_ROLES


def expected_claude_roles() -> tuple[str, ...]:
    return CLAUDE_HOOK_ROLES
