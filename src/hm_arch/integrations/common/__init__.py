"""Shared offline runtime for agent hook integrations.

Portable paths only: use ``HM_ARCH_DB_PATH`` or a caller-supplied path.
No machine-specific home-directory defaults.
"""

from __future__ import annotations

from .consolidate import run_idle_consolidation
from .paths import open_memory, resolve_db_path
from .payload import (
    extract_agent_message,
    extract_task_from_payload,
    extract_user_message,
)
from .recall import build_turn_start_context
from .record import record_turn_end

__all__ = [
    "build_turn_start_context",
    "extract_agent_message",
    "extract_task_from_payload",
    "extract_user_message",
    "open_memory",
    "record_turn_end",
    "resolve_db_path",
    "run_idle_consolidation",
]
