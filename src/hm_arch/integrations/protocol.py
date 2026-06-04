"""Stable JSON protocol for agent adapter operations.

Supported operations
--------------------
``recall``
    Search durable memory for task-relevant context before a host-agent turn.
``record``
    Persist user and assistant messages after a completed turn.
``consolidate``
    Run offline sleep consolidation during idle time or session boundaries.

Fail-open behavior
------------------
Adapter integrations must never block the host agent when HM-Arch fails.
Use :func:`fail_open_recall`, :func:`fail_open_record`, and
:func:`fail_open_consolidate` to return well-formed responses that signal
``ok=False`` while preserving safe empty defaults:

- Recall returns an empty ``context`` string.
- Record returns no ``memory_ids``.
- Consolidate returns zeroed consolidation counters.

Host adapters should log ``error`` for diagnostics but continue the turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ProtocolValidationError(ValueError):
    """Raised when an adapter payload is malformed or unsupported."""


class AdapterOperation(str, Enum):
    """Supported adapter protocol operations."""

    RECALL = "recall"
    RECORD = "record"
    CONSOLIDATE = "consolidate"


_SUPPORTED_OPERATIONS = {op.value for op in AdapterOperation}


def validate_operation(value: str) -> AdapterOperation:
    """Validate and normalize an operation name."""
    if not isinstance(value, str):
        raise ProtocolValidationError("operation must be a string")
    normalized = value.strip().lower()
    if normalized not in _SUPPORTED_OPERATIONS:
        raise ProtocolValidationError(
            f"Unsupported operation {value!r}. "
            f"Supported operations: {sorted(_SUPPORTED_OPERATIONS)}"
        )
    return AdapterOperation(normalized)


def _require_mapping(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ProtocolValidationError("Adapter payload must be a JSON object")
    return data


def _optional_str(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        if key not in data:
            continue
        value = data[key]
        if value is None:
            continue
        if not isinstance(value, str):
            raise ProtocolValidationError(f"{key} must be a string")
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _optional_int(data: dict[str, Any], key: str) -> int | None:
    if key not in data:
        return None
    value = data[key]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolValidationError(f"{key} must be an integer")
    return value


@dataclass(frozen=True)
class RecallRequest:
    """Recall durable memory relevant to the current task."""

    task: str
    top_k: int | None = None
    session_id: str | None = None


@dataclass(frozen=True)
class RecordRequest:
    """Record user and assistant messages from a completed turn."""

    user_message: str
    agent_message: str
    session_id: str | None = None


@dataclass(frozen=True)
class ConsolidateRequest:
    """Run offline consolidation."""

    session_id: str | None = None
    force: bool = False


@dataclass
class RecallResponse:
    """Recall operation result."""

    ok: bool
    context: str
    result_count: int
    truncated: bool
    error: str | None = None


@dataclass
class RecordResponse:
    """Record operation result."""

    ok: bool
    memory_ids: list[str]
    recorded_count: int
    error: str | None = None


@dataclass
class ConsolidateResponse:
    """Consolidation operation result."""

    ok: bool
    extracted_semantics: int
    merged_duplicates: int
    scheduled_reviews: int
    archived_to_l4: int
    error: str | None = None


def _parse_recall(data: dict[str, Any]) -> RecallRequest:
    task = _optional_str(data, "task", "prompt", "user_prompt", "user_message", "message")
    if task is None:
        raise ProtocolValidationError("recall requires a non-empty task or prompt")

    top_k = _optional_int(data, "top_k")
    if top_k is not None and top_k < 1:
        raise ProtocolValidationError("top_k must be >= 1")

    session_id = _optional_str(data, "session_id")
    return RecallRequest(task=task, top_k=top_k, session_id=session_id)


def _parse_record(data: dict[str, Any]) -> RecordRequest:
    user_message = _optional_str(
        data,
        "user_message",
        "user_prompt",
        "prompt",
        "message",
    )
    agent_message = _optional_str(
        data,
        "agent_message",
        "assistant_message",
        "last_assistant_message",
        "response",
        "output",
    )

    if user_message is None and agent_message is None:
        raise ProtocolValidationError(
            "record requires at least one non-empty user or agent message"
        )

    session_id = _optional_str(data, "session_id")
    return RecordRequest(
        user_message=user_message or "",
        agent_message=agent_message or "",
        session_id=session_id,
    )


def _parse_consolidate(data: dict[str, Any]) -> ConsolidateRequest:
    if "force" in data and not isinstance(data["force"], bool):
        raise ProtocolValidationError("force must be a boolean")
    session_id = _optional_str(data, "session_id")
    force = bool(data.get("force", False))
    return ConsolidateRequest(session_id=session_id, force=force)


def parse_adapter_request(
    data: dict[str, Any],
) -> RecallRequest | RecordRequest | ConsolidateRequest:
    """Parse and validate a JSON adapter request envelope."""
    payload = _require_mapping(data)
    if "operation" not in payload:
        raise ProtocolValidationError("operation is required")

    operation = validate_operation(payload["operation"])

    if operation is AdapterOperation.RECALL:
        return _parse_recall(payload)
    if operation is AdapterOperation.RECORD:
        return _parse_record(payload)
    return _parse_consolidate(payload)


def fail_open_recall(error: str) -> RecallResponse:
    """Return a fail-open recall response that does not block the host agent."""
    return RecallResponse(
        ok=False,
        context="",
        result_count=0,
        truncated=False,
        error=error,
    )


def fail_open_record(error: str) -> RecordResponse:
    """Return a fail-open record response that does not block the host agent."""
    return RecordResponse(
        ok=False,
        memory_ids=[],
        recorded_count=0,
        error=error,
    )


def fail_open_consolidate(error: str) -> ConsolidateResponse:
    """Return a fail-open consolidate response that does not block the host agent."""
    return ConsolidateResponse(
        ok=False,
        extracted_semantics=0,
        merged_duplicates=0,
        scheduled_reviews=0,
        archived_to_l4=0,
        error=error,
    )
