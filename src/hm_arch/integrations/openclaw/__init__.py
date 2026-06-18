"""OpenClaw memory plugin integration for HM-Arch."""

from __future__ import annotations

from .cli import run_openclaw_sidecar
from .config import (
    DEFAULT_DB_FILENAME,
    HM_ARCH_PLUGIN_ID,
    MemorySlotConflict,
    detect_memory_slot_conflict,
    load_openclaw_config,
    merge_plugin_settings,
    read_memory_slot,
    read_plugin_settings,
    resolve_bundled_openclaw_plugin_dir,
    resolve_db_path,
    resolve_openclaw_config_path,
    resolve_openclaw_state_dir,
    resolve_sidecar_command,
    write_openclaw_config,
)
from .handlers import SidecarHandlers
from .server import SidecarServer, configure_sidecar_logging

__all__ = [
    "DEFAULT_DB_FILENAME",
    "HM_ARCH_PLUGIN_ID",
    "MemorySlotConflict",
    "SidecarHandlers",
    "SidecarServer",
    "configure_sidecar_logging",
    "detect_memory_slot_conflict",
    "load_openclaw_config",
    "merge_plugin_settings",
    "read_memory_slot",
    "read_plugin_settings",
    "resolve_bundled_openclaw_plugin_dir",
    "resolve_db_path",
    "resolve_openclaw_config_path",
    "resolve_openclaw_state_dir",
    "resolve_sidecar_command",
    "run_openclaw_sidecar",
    "write_openclaw_config",
]
