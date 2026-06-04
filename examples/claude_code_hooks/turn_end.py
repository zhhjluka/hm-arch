#!/usr/bin/env python3
"""Claude Code turn-end hook: record user and assistant messages.

Wire to ``Stop`` in ``.claude/settings.json``.
"""

from __future__ import annotations

from hm_arch.integrations.claude_code import main_turn_end

if __name__ == "__main__":
    raise SystemExit(main_turn_end())
