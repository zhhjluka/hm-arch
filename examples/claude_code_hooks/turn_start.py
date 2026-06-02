#!/usr/bin/env python3
"""Claude Code turn-start hook: inject retrieved memory context.

Wire to ``UserPromptSubmit`` in ``.claude/settings.json``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from examples.claude_code_hooks.hooks import main_turn_start

if __name__ == "__main__":
    raise SystemExit(main_turn_start())
