"""Claude Code hook adapter for HM-Arch memory."""

from .hooks import (
    claude_idle_consolidation_hook,
    claude_turn_end_hook,
    claude_turn_start_hook,
    main_idle_consolidation,
    main_turn_end,
    main_turn_start,
)

__all__ = [
    "claude_idle_consolidation_hook",
    "claude_turn_end_hook",
    "claude_turn_start_hook",
    "main_idle_consolidation",
    "main_turn_end",
    "main_turn_start",
]
