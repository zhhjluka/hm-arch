#!/usr/bin/env python3
"""Claude Code turn-start hook: inject retrieved memory context.

Wire to ``UserPromptSubmit`` in ``.claude/settings.json``.
"""

from __future__ import annotations

from hm_arch.integrations.claude_code import main_turn_start

if __name__ == "__main__":
    raise SystemExit(main_turn_start())
