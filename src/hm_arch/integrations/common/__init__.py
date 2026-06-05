"""Shared offline runtime for agent hook integrations.

Portable paths only: use ``HM_ARCH_DB_PATH`` or a caller-supplied path.
No machine-specific home-directory defaults.
"""

from __future__ import annotations

from .consolidate import run_idle_consolidation
from .io import read_hook_payload
from .paths import open_memory, resolve_db_path
from .payload import (
    extract_agent_message,
    extract_task_from_payload,
    extract_user_message,
)
from .recall import (
    apply_recall_context_limits,
    build_turn_start_context,
    deduplicate_recall_hits,
    truncate_recall_context,
)
from .record import record_turn_end

__all__ = [
    "apply_recall_context_limits",
    "build_turn_start_context",
    "deduplicate_recall_hits",
    "truncate_recall_context",
    "extract_agent_message",
    "extract_task_from_payload",
    "extract_user_message",
    "open_memory",
    "read_hook_payload",
    "record_turn_end",
    "resolve_db_path",
    "run_idle_consolidation",
]
