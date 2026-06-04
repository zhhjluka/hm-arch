"""Claude Code hook handlers (stdin JSON in, stdout JSON out)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hm_arch.integrations.common import (
    build_turn_start_context,
    extract_agent_message,
    extract_task_from_payload,
    extract_user_message,
    open_memory,
    record_turn_end,
    run_idle_consolidation,
)


def _read_payload() -> dict[str, Any]:
    if sys.stdin.isatty():
        return {}
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise TypeError("Hook payload must be a JSON object")
    return data


def _emit_claude_context(context: str) -> None:
    """Claude Code hook output for context injection events."""
    payload: dict[str, Any] = {}
    if context.strip():
        payload = {
            "hookSpecificOutput": {
                "additionalContext": context,
            }
        }
    print(json.dumps(payload))


def claude_turn_start_hook(
    payload: dict[str, Any] | None = None,
    *,
    db_path: str | None = None,
) -> str:
    """Turn-start hook: return memory context for the submitted prompt."""
    payload = payload if payload is not None else _read_payload()
    task = extract_task_from_payload(payload)

    with open_memory(db_path) as memory:
        context = build_turn_start_context(memory, task)

    if payload:
        _emit_claude_context(context)
    return context


def claude_turn_end_hook(
    payload: dict[str, Any] | None = None,
    *,
    db_path: str | None = None,
) -> list[str]:
    """Turn-end hook: record conversation messages after a response."""
    payload = payload if payload is not None else _read_payload()
    user_message = extract_user_message(payload)
    agent_message = extract_agent_message(payload)

    with open_memory(db_path) as memory:
        memory_ids = record_turn_end(memory, user_message, agent_message)

    if payload:
        # Stop hooks may emit stderr or JSON; keep stdout minimal to avoid blocking.
        print(json.dumps({"continue": True, "recorded": len(memory_ids)}))
    return memory_ids


def claude_idle_consolidation_hook(
    payload: dict[str, Any] | None = None,
    *,
    db_path: str | None = None,
) -> dict[str, int]:
    """Idle hook: consolidate when Claude Code reports teammate idle."""
    payload = payload if payload is not None else _read_payload()

    with open_memory(db_path) as memory:
        report = run_idle_consolidation(memory)

    summary = {
        "extracted_semantics": report.extracted_semantics,
        "merged_duplicates": report.merged_duplicates,
        "scheduled_reviews": report.scheduled_reviews,
        "archived_to_l4": report.archived_to_l4,
    }
    if payload:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "additionalContext": (
                            "HM-Arch idle consolidation finished "
                            f"(extracted={report.extracted_semantics})."
                        )
                    }
                }
            )
        )
    return summary


def main_turn_start() -> int:
    claude_turn_start_hook()
    return 0


def main_turn_end() -> int:
    claude_turn_end_hook()
    return 0


def main_idle_consolidation() -> int:
    claude_idle_consolidation_hook()
    return 0
