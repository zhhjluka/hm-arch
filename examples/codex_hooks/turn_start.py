#!/usr/bin/env python3
"""Codex turn-start hook: inject retrieved memory context.

Wire to ``UserPromptSubmit`` (or ``SessionStart``) in ``.codex/hooks.json``.
Reads JSON from stdin; prints Codex ``hookSpecificOutput.additionalContext``.
"""

from __future__ import annotations

from hm_arch.integrations.codex import main_turn_start

if __name__ == "__main__":
    raise SystemExit(main_turn_start())
