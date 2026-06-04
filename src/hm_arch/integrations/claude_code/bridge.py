"""Claude Code hook bridge entrypoints invoked by installed ``settings.json`` commands."""

from __future__ import annotations

from .hooks import (
    main_idle_consolidation,
    main_turn_end,
    main_turn_start,
)


def run_claude_recall() -> int:
    return main_turn_start()


def run_claude_record() -> int:
    return main_turn_end()


def run_claude_consolidate() -> int:
    return main_idle_consolidation()
