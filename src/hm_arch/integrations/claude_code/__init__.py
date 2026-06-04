"""Claude Code hook adapter and installer for HM-Arch memory."""

from .hooks import (
    claude_idle_consolidation_hook,
    claude_turn_end_hook,
    claude_turn_start_hook,
    main_idle_consolidation,
    main_turn_end,
    main_turn_start,
)
from .installer import InstallScope, install_claude_code, uninstall_claude_code

__all__ = [
    "InstallScope",
    "claude_idle_consolidation_hook",
    "claude_turn_end_hook",
    "claude_turn_start_hook",
    "install_claude_code",
    "main_idle_consolidation",
    "main_turn_end",
    "main_turn_start",
    "uninstall_claude_code",
]
