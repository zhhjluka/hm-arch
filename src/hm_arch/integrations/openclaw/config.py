"""OpenClaw configuration helpers for HM-Arch memory plugin registration.

Detects an already configured memory slot and refuses to silently replace it
when ``plugins.slots.memory`` points at another backend.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from hm_arch.integrations.executable import resolve_hm_arch_command_prefix

HM_ARCH_PLUGIN_ID = "memory-hm-arch"
DEFAULT_DB_FILENAME = "hm_arch_memory.db"
_EMPTY_SLOT_VALUES = frozenset({None, "", "none"})


@dataclass(frozen=True)
class MemorySlotConflict(Exception):
    """Raised when OpenClaw already has a different memory plugin selected."""

    configured_slot: str
    requested_slot: str = HM_ARCH_PLUGIN_ID

    def __str__(self) -> str:
        return (
            f"OpenClaw plugins.slots.memory is already set to "
            f"{self.configured_slot!r}; refusing to silently replace it with "
            f"{self.requested_slot!r}. Set plugins.slots.memory explicitly if "
            "you intend to switch memory providers."
        )


def resolve_openclaw_state_dir() -> Path:
    """Return the OpenClaw state directory from env or the default."""
    raw = os.environ.get("OPENCLAW_STATE_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".openclaw"


def resolve_openclaw_config_path(*, global_install: bool) -> Path:
    """Resolve the OpenClaw config file for project or global scope."""
    config_env = os.environ.get("OPENCLAW_CONFIG_PATH", "").strip()
    if config_env:
        return Path(config_env).expanduser()
    if global_install:
        return resolve_openclaw_state_dir() / "openclaw.json"
    return Path.cwd() / ".openclaw" / "openclaw.json"


def resolve_openclaw_config_root(*, global_install: bool) -> Path:
    """Return the directory that owns OpenClaw config and extensions."""
    return resolve_openclaw_config_path(global_install=global_install).parent


def resolve_sidecar_command() -> tuple[str, ...]:
    """Return the HM-Arch sidecar command prefix used by the OpenClaw plugin."""
    return (*resolve_hm_arch_command_prefix(), "openclaw", "sidecar")


def _normalize_slot(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def read_memory_slot(config: Mapping[str, Any] | None) -> str | None:
    """Return the configured ``plugins.slots.memory`` value, if any."""
    if not config:
        return None
    plugins = config.get("plugins")
    if not isinstance(plugins, dict):
        return None
    slots = plugins.get("slots")
    if not isinstance(slots, dict):
        return None
    return _normalize_slot(slots.get("memory"))


def detect_memory_slot_conflict(
    config: Mapping[str, Any] | None,
    *,
    requested_slot: str = HM_ARCH_PLUGIN_ID,
) -> MemorySlotConflict | None:
    """Return a conflict when another memory plugin slot is already active."""
    configured = read_memory_slot(config)
    if configured is None or configured in _EMPTY_SLOT_VALUES:
        return None
    if configured == requested_slot:
        return None
    return MemorySlotConflict(
        configured_slot=configured,
        requested_slot=requested_slot,
    )


def read_plugin_settings(config: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return ``plugins.entries.memory-hm-arch.config`` settings."""
    if not config:
        return {}
    plugins = config.get("plugins")
    if not isinstance(plugins, dict):
        return {}
    entries = plugins.get("entries")
    if not isinstance(entries, dict):
        return {}
    entry = entries.get(HM_ARCH_PLUGIN_ID)
    if not isinstance(entry, dict):
        return {}
    section = entry.get("config")
    if isinstance(section, dict):
        return dict(section)
    return {}


def resolve_db_path(
    openclaw_root: str | Path,
    plugin_settings: Mapping[str, Any] | None = None,
) -> str:
    """Resolve the HM-Arch SQLite path for an OpenClaw installation."""
    root = Path(openclaw_root).expanduser()
    settings = dict(plugin_settings or {})
    raw = settings.get("dbPath")
    if isinstance(raw, str) and raw.strip():
        path = raw.strip()
        state_dir = str(resolve_openclaw_state_dir())
        path = path.replace("$OPENCLAW_STATE_DIR", state_dir)
        path = path.replace("${OPENCLAW_STATE_DIR}", state_dir)
        path = path.replace("~", str(Path.home()))
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        return str(candidate)
    return str(root / DEFAULT_DB_FILENAME)


def load_openclaw_config(path: Path) -> dict[str, Any]:
    """Load an OpenClaw ``openclaw.json`` document."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object at the top level")
    return data


def write_openclaw_config(path: Path, config: dict[str, Any]) -> None:
    """Write an OpenClaw config file, preserving JSON formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def merge_plugin_settings(
    config: dict[str, Any],
    values: Mapping[str, Any],
    *,
    plugin_id: str = HM_ARCH_PLUGIN_ID,
) -> dict[str, Any]:
    """Merge HM-Arch plugin settings without overwriting an unrelated memory slot."""
    merged = dict(config)
    plugins = merged.setdefault("plugins", {})
    if not isinstance(plugins, dict):
        raise ValueError("config.plugins must be an object")
    entries = plugins.setdefault("entries", {})
    if not isinstance(entries, dict):
        raise ValueError("config.plugins.entries must be an object")
    entry = entries.setdefault(plugin_id, {})
    if not isinstance(entry, dict):
        raise ValueError(f"config.plugins.entries.{plugin_id} must be an object")
    entry["enabled"] = True
    section = entry.setdefault("config", {})
    if not isinstance(section, dict):
        raise ValueError(f"config.plugins.entries.{plugin_id}.config must be an object")
    section.update(dict(values))

    existing_slot = read_memory_slot(merged)
    if existing_slot and existing_slot not in _EMPTY_SLOT_VALUES and existing_slot != plugin_id:
        return merged

    slots = plugins.setdefault("slots", {})
    if not isinstance(slots, dict):
        raise ValueError("config.plugins.slots must be an object")
    current_slot = _normalize_slot(slots.get("memory"))
    if current_slot is None or current_slot in _EMPTY_SLOT_VALUES:
        slots["memory"] = plugin_id
    return merged
