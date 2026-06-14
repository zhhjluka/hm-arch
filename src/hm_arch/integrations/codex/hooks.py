"""Codex-oriented hook handlers (stdin JSON in, stdout JSON out)."""

from __future__ import annotations

import json
from typing import Any

from hm_arch.integrations.common import (
    apply_recall_context_limits,
    build_turn_start_context,
    extract_agent_message,
    extract_task_from_payload,
    extract_user_message,
    open_memory,
    read_hook_payload,
    record_turn_end,
    run_idle_consolidation,
)
from hm_arch.integrations.config import IntegrationConfig


def _emit_additional_context(context: str, *, hook_event_name: str) -> None:
    """Codex hook output: inject memory text into the model context."""
    payload: dict[str, Any] = {}
    if context.strip():
        payload = {
            "hookSpecificOutput": {
                "hookEventName": hook_event_name,
                "additionalContext": context,
            }
        }
    print(json.dumps(payload))


def codex_turn_start_hook(
    payload: dict[str, Any] | None = None,
    *,
    db_path: str | None = None,
) -> str:
    """Turn-start hook: return memory context for the current task/prompt."""
    payload = payload if payload is not None else read_hook_payload()
    task = extract_task_from_payload(payload)

    config = IntegrationConfig(db_path=db_path) if db_path else IntegrationConfig()
    with open_memory(db_path, config=config) as memory:
        context, _ = apply_recall_context_limits(
            build_turn_start_context(
                memory,
                task,
                top_k=config.recall_top_k,
            ),
            config.max_context_chars,
        )

    if payload:
        _emit_additional_context(context, hook_event_name="UserPromptSubmit")
    return context


def codex_turn_end_hook(
    payload: dict[str, Any] | None = None,
    *,
    db_path: str | None = None,
) -> list[str]:
    """Turn-end hook: record user and assistant messages."""
    payload = payload if payload is not None else read_hook_payload()
    user_message = extract_user_message(payload)
    agent_message = extract_agent_message(payload)

    with open_memory(db_path) as memory:
        memory_ids = record_turn_end(memory, user_message, agent_message)

    if payload:
        print(
            json.dumps(
                {
                    "systemMessage": (
                        f"HM-Arch recorded {len(memory_ids)} episodic message(s)."
                    )
                }
            )
        )
    return memory_ids


def codex_idle_consolidation_hook(
    payload: dict[str, Any] | None = None,
    *,
    db_path: str | None = None,
) -> dict[str, int]:
    """Idle hook: run consolidation without requiring conversation input."""
    payload = payload if payload is not None else read_hook_payload()

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
                    "systemMessage": (
                        "HM-Arch idle consolidation complete: "
                        f"extracted={report.extracted_semantics}, "
                        f"reviews={report.scheduled_reviews}"
                    )
                }
            )
        )
    return summary


def main_turn_start() -> int:
    codex_turn_start_hook()
    return 0


def main_turn_end() -> int:
    codex_turn_end_hook()
    return 0


def main_idle_consolidation() -> int:
    codex_idle_consolidation_hook()
    return 0
