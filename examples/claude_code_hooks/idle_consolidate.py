#!/usr/bin/env python3
"""Claude Code idle consolidation hook.

Wire to ``TeammateIdle`` in ``.claude/settings.json``.
"""

from __future__ import annotations

from hm_arch.integrations.claude_code import main_idle_consolidation

if __name__ == "__main__":
    raise SystemExit(main_idle_consolidation())
