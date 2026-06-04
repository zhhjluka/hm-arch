#!/usr/bin/env python3
"""Codex turn-end hook: record user and assistant messages.

Wire to ``Stop`` in ``.codex/hooks.json``.
"""

from __future__ import annotations

from hm_arch.integrations.codex import main_turn_end

if __name__ == "__main__":
    raise SystemExit(main_turn_end())
