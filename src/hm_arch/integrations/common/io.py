"""Stdin JSON helpers shared by host hook adapters."""

from __future__ import annotations

import json
import sys
from typing import Any


def read_hook_payload() -> dict[str, Any]:
    """Read a hook JSON object from stdin, or return {} when interactive/empty."""
    if sys.stdin.isatty():
        return {}
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise TypeError("Hook payload must be a JSON object")
    return data
