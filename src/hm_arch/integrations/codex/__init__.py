"""Codex CLI hook adapter and installer for HM-Arch memory."""

from .hooks import (
    codex_idle_consolidation_hook,
    codex_turn_end_hook,
    codex_turn_start_hook,
    main_idle_consolidation,
    main_turn_end,
    main_turn_start,
)
from .installer import InstallScope, install_codex, uninstall_codex

__all__ = [
    "InstallScope",
    "codex_idle_consolidation_hook",
    "codex_turn_end_hook",
    "codex_turn_start_hook",
    "install_codex",
    "main_idle_consolidation",
    "main_turn_end",
    "main_turn_start",
    "uninstall_codex",
]
