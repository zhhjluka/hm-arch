"""Best-effort field extraction from hook JSON payloads."""

from __future__ import annotations


def extract_task_from_payload(payload: dict) -> str:
    """Best-effort task/prompt extraction from hook JSON payloads."""
    for key in (
        "prompt",
        "user_prompt",
        "user_message",
        "message",
        "task",
        "input",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def extract_user_message(payload: dict) -> str:
    for key in ("user_message", "user_prompt", "prompt", "message"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def extract_agent_message(payload: dict) -> str:
    for key in (
        "last_assistant_message",
        "assistant_message",
        "agent_message",
        "response",
        "output",
    ):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""
