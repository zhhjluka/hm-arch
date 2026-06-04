"""Codex hook bridge entrypoints invoked by installed ``hooks.json`` commands."""

from __future__ import annotations

from .hooks import (
    main_idle_consolidation,
    main_turn_end,
    main_turn_start,
)


def run_codex_recall() -> int:
    return main_turn_start()


def run_codex_record() -> int:
    return main_turn_end()


def run_codex_consolidate() -> int:
    return main_idle_consolidation()
