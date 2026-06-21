"""Sanitized failure provenance for benchmark query records."""

from __future__ import annotations

import re
from typing import Any

from .types import AgentOutcome, RecallOutcome

_SECRET_PATTERNS = (
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"(?i)(api[_-]?key|authorization|bearer|token)[=:\s]+\S+"),
    re.compile(r"(?i)(password|secret)[=:\s]+\S+"),
)


def sanitize_failure_text(text: str | None, *, max_len: int = 500) -> str | None:
    """Redact likely secrets and cap length for committed benchmark artifacts."""
    if not text:
        return None
    cleaned = text.strip()
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub("<redacted>", cleaned)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > max_len:
        return cleaned[: max_len - 3] + "..."
    return cleaned or None


def _agent_failure_category(agent_out: AgentOutcome) -> str | None:
    if agent_out.failure_count == 0:
        return None
    metadata = agent_out.metadata or {}
    if metadata.get("timed_out"):
        return "agent_timeout"
    if metadata.get("exit_code") is not None:
        return "agent_cli_exit"
    if agent_out.error:
        return "agent_error"
    return "agent_failure"


def build_query_failure_provenance(
    *,
    recall: RecallOutcome,
    agent_out: AgentOutcome,
) -> dict[str, Any]:
    """Build per-query failure fields for QueryRecord and JSONL output."""
    recall_reason = sanitize_failure_text(recall.error) if recall.failure_count else None
    agent_reason = sanitize_failure_text(agent_out.error) if agent_out.failure_count else None
    metadata = agent_out.metadata or {}

    parts: list[str] = []
    if recall_reason:
        parts.append(f"recall: {recall_reason}")
    if agent_reason:
        parts.append(f"agent: {agent_reason}")

    category: str | None = None
    if recall.failure_count and agent_out.failure_count:
        category = "recall_and_agent"
    elif recall.failure_count:
        category = "recall_error"
    else:
        category = _agent_failure_category(agent_out)

    return {
        "failure_reason": " | ".join(parts) if parts else None,
        "failure_category": category,
        "recall_failure_reason": recall_reason,
        "agent_failure_reason": agent_reason,
        "agent_exit_code": metadata.get("exit_code"),
        "agent_timed_out": metadata.get("timed_out"),
    }
