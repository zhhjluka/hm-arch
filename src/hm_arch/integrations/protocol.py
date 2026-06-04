"""Typed request and response models for the agent adapter JSON protocol."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Literal, Union

from .errors import FAIL_OPEN_ERROR_CODES

_SUPPORTED_OPERATIONS = frozenset({"recall", "record", "consolidate"})


class AgentOperation(str, Enum):
    """Supported adapter operations."""

    RECALL = "recall"
    RECORD = "record"
    CONSOLIDATE = "consolidate"


class ProtocolValidationError(ValueError):
    """Raised when an adapter payload is malformed or unsupported."""


@dataclass(frozen=True)
class RecallRequest:
    operation: Literal["recall"] = "recall"
    task: str = ""
    top_k: int | None = None


@dataclass(frozen=True)
class RecordRequest:
    operation: Literal["record"] = "record"
    user_message: str = ""
    agent_message: str = ""


@dataclass(frozen=True)
class ConsolidateRequest:
    operation: Literal["consolidate"] = "consolidate"


AdapterRequest = Union[RecallRequest, RecordRequest, ConsolidateRequest]


@dataclass
class RecallResponse:
    ok: Literal[True] = True
    operation: Literal["recall"] = "recall"
    context: str = ""
    hit_count: int = 0
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RecordResponse:
    ok: Literal[True] = True
    operation: Literal["record"] = "record"
    memory_ids: list[str] | None = None

    def __post_init__(self) -> None:
        if self.memory_ids is None:
            object.__setattr__(self, "memory_ids", [])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConsolidateResponse:
    ok: Literal[True] = True
    operation: Literal["consolidate"] = "consolidate"
    skipped: bool = False
    extracted_semantics: int = 0
    merged_duplicates: int = 0
    resolved_conflicts: int = 0
    archived_to_l4: int = 0
    scheduled_reviews: int = 0
    marked_deletable: int = 0
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


AdapterSuccessResponse = Union[RecallResponse, RecordResponse, ConsolidateResponse]


def _require_mapping(payload: Any, *, operation: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ProtocolValidationError(
            f"Expected JSON object for {operation!r}, got {type(payload).__name__}"
        )
    return payload


def _require_str(value: Any, field: str, *, operation: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ProtocolValidationError(
            f"Field {field!r} for {operation!r} must be a string, "
            f"got {type(value).__name__}"
        )
    return value


def _require_optional_int(value: Any, field: str, *, operation: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolValidationError(
            f"Field {field!r} for {operation!r} must be an integer, "
            f"got {type(value).__name__}"
        )
    if value < 1:
        raise ProtocolValidationError(
            f"Field {field!r} for {operation!r} must be >= 1"
        )
    return value


def parse_adapter_request(payload: Any) -> AdapterRequest:
    """Validate *payload* and return a typed request.

    Raises
    ------
    ProtocolValidationError
        When the payload is not a mapping, omits ``operation``, uses an
        unsupported operation name, or has invalid field types.
    """
    data = _require_mapping(payload, operation="adapter")
    operation_raw = data.get("operation")
    if operation_raw is None:
        raise ProtocolValidationError("Missing required field 'operation'")
    if not isinstance(operation_raw, str):
        raise ProtocolValidationError(
            f"Field 'operation' must be a string, got {type(operation_raw).__name__}"
        )
    operation = operation_raw.strip().lower()
    if operation not in _SUPPORTED_OPERATIONS:
        raise ProtocolValidationError(
            f"Unsupported operation {operation_raw!r}. "
            f"Supported: {sorted(_SUPPORTED_OPERATIONS)}"
        )

    if operation == AgentOperation.RECALL.value:
        task = _require_str(data.get("task"), "task", operation=operation)
        top_k = _require_optional_int(data.get("top_k"), "top_k", operation=operation)
        return RecallRequest(task=task, top_k=top_k)

    if operation == AgentOperation.RECORD.value:
        user_message = _require_str(
            data.get("user_message"), "user_message", operation=operation
        )
        agent_message = _require_str(
            data.get("agent_message"), "agent_message", operation=operation
        )
        return RecordRequest(
            user_message=user_message,
            agent_message=agent_message,
        )

    return ConsolidateRequest()


def operation_from_payload(payload: Any) -> str:
    """Best-effort operation name for fail-open responses."""
    if isinstance(payload, dict):
        raw = payload.get("operation")
        if isinstance(raw, str) and raw.strip():
            return raw.strip().lower()
    if isinstance(payload, RecallRequest):
        return AgentOperation.RECALL.value
    if isinstance(payload, RecordRequest):
        return AgentOperation.RECORD.value
    if isinstance(payload, ConsolidateRequest):
        return AgentOperation.CONSOLIDATE.value
    return "unknown"


__all__ = [
    "AgentOperation",
    "AdapterRequest",
    "AdapterSuccessResponse",
    "ConsolidateRequest",
    "ConsolidateResponse",
    "ProtocolValidationError",
    "RecallRequest",
    "RecallResponse",
    "RecordRequest",
    "RecordResponse",
    "operation_from_payload",
    "parse_adapter_request",
]
