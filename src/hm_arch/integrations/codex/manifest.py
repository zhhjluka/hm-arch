"""HM-Arch-owned Codex hook manifest helpers."""

from __future__ import annotations

import shutil
import sys
from typing import Any

HM_ARCH_OWNER = "hm-arch"
HM_ARCH_META_KEY = "hmArch"

RECALL_EVENT = "UserPromptSubmit"
STOP_EVENT = "Stop"

HOOK_ROLES = ("recall", "record", "consolidate")

_ROLE_BY_EVENT: dict[str, tuple[str, ...]] = {
    RECALL_EVENT: ("recall",),
    STOP_EVENT: ("record", "consolidate"),
}


def resolve_hm_arch_codex_command(role: str) -> str:
    """Return a shell command that runs the packaged Codex hook bridge."""
    subcommand = ("codex", role)
    executable = shutil.which("hm-arch")
    if executable:
        return " ".join((executable, *subcommand))
    return " ".join((sys.executable, "-m", "hm_arch.integrations.cli", *subcommand))


def hook_metadata(role: str) -> dict[str, str]:
    return {"owner": HM_ARCH_OWNER, "role": role}


def is_hm_arch_hook(hook: dict[str, Any]) -> bool:
    """Return True when *hook* is owned by the HM-Arch Codex installer."""
    meta = hook.get(HM_ARCH_META_KEY)
    if isinstance(meta, dict) and meta.get("owner") == HM_ARCH_OWNER:
        return True
    command = hook.get("command")
    if isinstance(command, str):
        if "hm-arch codex" in command:
            return True
        if "hm_arch.integrations.cli" in command and " codex " in command:
            return True
    return False


def build_hook_definition(role: str) -> dict[str, Any]:
    """Build one Codex command hook entry for *role*."""
    command = resolve_hm_arch_codex_command(role)
    hook: dict[str, Any] = {
        "type": "command",
        "command": command,
        HM_ARCH_META_KEY: hook_metadata(role),
    }
    if role == "recall":
        hook["timeout"] = 15
        hook["statusMessage"] = "Loading HM-Arch context"
    elif role == "record":
        hook["timeout"] = 15
        hook["statusMessage"] = "Recording HM-Arch turn memory"
    else:
        hook["timeout"] = 120
        hook["statusMessage"] = "HM-Arch consolidation"
    return hook


def roles_for_event(event: str) -> tuple[str, ...]:
    return _ROLE_BY_EVENT.get(event, ())
