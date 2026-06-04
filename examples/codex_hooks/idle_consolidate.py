#!/usr/bin/env python3
"""Codex idle consolidation hook.

Run during idle periods or from a long-timeout ``Stop`` hook in ``.codex/hooks.json``.
"""

from __future__ import annotations

from hm_arch.integrations.codex import main_idle_consolidation

if __name__ == "__main__":
    raise SystemExit(main_idle_consolidation())
