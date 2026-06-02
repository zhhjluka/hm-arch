#!/usr/bin/env python3
"""Codex idle hook: run offline consolidation when the agent is idle.

Wire to a long-timeout ``Stop`` companion or a scheduled wrapper script.
Safe to run on an empty memory store.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from examples.codex_hooks.hooks import main_idle_consolidation

if __name__ == "__main__":
    raise SystemExit(main_idle_consolidation())
