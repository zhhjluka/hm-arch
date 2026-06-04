"""Conversation message helpers for Hermes lifecycle hooks."""

from __future__ import annotations

from typing import Any, Mapping


def message_text(message: Mapping[str, Any]) -> str:
    """Extract plain text from an OpenAI-style conversation message."""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"].strip())
        return "\n".join(part for part in parts if part)
    return ""


def iter_turn_pairs(
    messages: list[Mapping[str, Any]],
) -> list[tuple[str, str]]:
    """Pair consecutive user and assistant messages from a transcript."""
    pairs: list[tuple[str, str]] = []
    pending_user = ""
    for message in messages:
        role = str(message.get("role", "")).lower()
        text = message_text(message)
        if not text:
            continue
        if role == "user":
            pending_user = text
            continue
        if role == "assistant" and pending_user:
            pairs.append((pending_user, text))
            pending_user = ""
    return pairs


def summarize_messages_for_compression(
    messages: list[Mapping[str, Any]],
    *,
    max_chars: int = 4000,
) -> str:
    """Build a compact transcript snippet for pre-compression persistence."""
    lines: list[str] = []
    for message in messages:
        role = str(message.get("role", "")).lower()
        text = message_text(message)
        if role not in {"user", "assistant"} or not text:
            continue
        lines.append(f"{role}: {text}")
    blob = "\n".join(lines).strip()
    if len(blob) <= max_chars:
        return blob
    return blob[: max_chars - 3].rstrip() + "..."
