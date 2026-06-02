#!/usr/bin/env python3
"""Codex turn-start hook: inject retrieved memory context.

Wire to ``UserPromptSubmit`` (or ``SessionStart``) in ``.codex/hooks.json``.
Reads JSON from stdin; prints Codex ``hookSpecificOutput.additionalContext``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from examples.codex_hooks.hooks import main_turn_start

if __name__ == "__main__":
    raise SystemExit(main_turn_start())
