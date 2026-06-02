#!/usr/bin/env python3
"""Codex turn-end hook: record user and assistant messages.

Wire to ``Stop`` in ``.codex/hooks.json``. Reads JSON from stdin.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from examples.codex_hooks.hooks import main_turn_end

if __name__ == "__main__":
    raise SystemExit(main_turn_end())
