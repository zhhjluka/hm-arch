"""Sidecar JSONL stdio protocol types, parsing, and fail-open helpers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ProtocolValidationError(ValueError):
    """Raised when a sidecar envelope or params payload is malformed."""


CURRENT_PROTOCOL_VERSION = "1.0"
DEFAULT_SERVER_CAPABILITIES = (
    "telemetry.v1",
    "forget.by_query.v1",
    "health.deep.v1",
)


class SidecarOperation(str, Enum):
    """Supported sidecar protocol operations."""

    INITIALIZE = "initialize"
    HEALTH = "health"
    SEARCH = "search"
    REMEMBER = "remember"
    FORGET = "forget"
    RECORD_TURN = "record_turn"
    CONSOLIDATE = "consolidate"
    SHUTDOWN = "shutdown"


SUPPORTED_OPERATIONS = {op.value for op in SidecarOperation}
FAIL_OPEN_OPERATIONS = {
    SidecarOperation.SEARCH.value,
    SidecarOperation.REMEMBER.value,
    SidecarOperation.RECORD_TURN.value,
}


@dataclass(frozen=True)
class SidecarError:
    """Structured error returned when ``ok`` is false."""

    code: str
    message: str
    retryable: bool
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SidecarTelemetry:
    """Optional benchmark telemetry on responses."""

    query_latency_ms: float | None = None
    hit_count: int | None = None
    returned_characters: int | None = None
    returned_tokens: int | None = None
    storage_latency_ms: float | None = None


@dataclass(frozen=True)
class InitializeParams:
    db_path: str
    config: dict[str, Any] = field(default_factory=dict)
    client_capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class HealthParams:
    deep: bool = False


@dataclass(frozen=True)
class SearchParams:
    query: str
    top_k: int | None = None
    session_id: str | None = None
    max_context_chars: int | None = None


@dataclass(frozen=True)
class RememberParams:
    content: str
    event_type: str | None = None
    importance: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None


@dataclass(frozen=True)
class ForgetParams:
    memory_ids: tuple[str, ...] = ()
    query: str | None = None


@dataclass(frozen=True)
class RecordTurnParams:
    user_message: str = ""
    agent_message: str = ""
    session_id: str | None = None


@dataclass(frozen=True)
class ConsolidateParams:
    force: bool = False
    session_id: str | None = None


SidecarParams = (
    InitializeParams
    | HealthParams
    | SearchParams
    | RememberParams
    | ForgetParams
    | RecordTurnParams
    | ConsolidateParams
    | dict[str, Any]
)


@dataclass(frozen=True)
class SidecarRequest:
    protocol_version: str
    correlation_id: str
    operation: SidecarOperation
    params: SidecarParams
    timeout_ms: int | None = None


@dataclass(frozen=True)
class SearchHit:
    memory_id: str
    layer: int
    content: str
    score: float
    retention: float


@dataclass(frozen=True)
class InitializeResult:
    ready: bool
    negotiated_protocol_version: str
    server_capabilities: tuple[str, ...]
    negotiated_capabilities: tuple[str, ...]
    db_path: str


@dataclass(frozen=True)
class HealthResult:
    status: str
    db_reachable: bool
    stats: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchResult:
    context: str
    hits: tuple[SearchHit, ...]
    result_count: int
    truncated: bool


@dataclass(frozen=True)
class RememberResult:
    memory_id: str | None
    recorded: bool


@dataclass(frozen=True)
class ForgetResult:
    forgotten_count: int
    memory_ids: tuple[str, ...]


@dataclass(frozen=True)
class RecordTurnResult:
    memory_ids: tuple[str, ...]
    recorded_count: int


@dataclass(frozen=True)
class ConsolidateResult:
    extracted_semantics: int
    merged_duplicates: int
    scheduled_reviews: int
    archived_to_l4: int


@dataclass(frozen=True)
class ShutdownResult:
    shutdown_ack: bool


SidecarResult = (
    InitializeResult
    | HealthResult
    | SearchResult
    | RememberResult
    | ForgetResult
    | RecordTurnResult
    | ConsolidateResult
    | ShutdownResult
    | dict[str, Any]
)


@dataclass(frozen=True)
class SidecarResponse:
    protocol_version: str
    correlation_id: str
    operation: SidecarOperation
    ok: bool
    result: SidecarResult
    error: SidecarError | None = None
    telemetry: SidecarTelemetry | None = None


def validate_operation(value: str) -> SidecarOperation:
    if not isinstance(value, str):
        raise ProtocolValidationError("operation must be a string")
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_OPERATIONS:
        raise ProtocolValidationError(
            f"Unsupported operation {value!r}. "
            f"Supported operations: {sorted(SUPPORTED_OPERATIONS)}"
        )
    return SidecarOperation(normalized)


def _parse_version(version: str) -> tuple[int, int]:
    parts = version.split(".", 1)
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise ProtocolValidationError(
            f"protocol_version must be MAJOR.MINOR, got {version!r}"
        )
    return int(parts[0]), int(parts[1])


def validate_protocol_version(version: str, *, server_version: str = CURRENT_PROTOCOL_VERSION) -> None:
    client = _parse_version(version)
    server = _parse_version(server_version)
    if client[0] != server[0]:
        raise ProtocolValidationError(
            f"Incompatible protocol major version {version!r}; server is {server_version!r}"
        )


def negotiate_protocol_version(
    client_version: str,
    *,
    server_version: str = CURRENT_PROTOCOL_VERSION,
) -> str:
    validate_protocol_version(client_version, server_version=server_version)
    client = _parse_version(client_version)
    server = _parse_version(server_version)
    major = client[0]
    minor = min(client[1], server[1])
    return f"{major}.{minor}"


def negotiate_capabilities(
    client_capabilities: list[str] | tuple[str, ...],
    *,
    server_capabilities: list[str] | tuple[str, ...] = DEFAULT_SERVER_CAPABILITIES,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    server = tuple(server_capabilities)
    client = tuple(client_capabilities)
    negotiated = tuple(tag for tag in client if tag in server)
    return server, negotiated


def structured_error(
    code: str,
    message: str,
    *,
    retryable: bool,
    details: dict[str, Any] | None = None,
) -> SidecarError:
    return SidecarError(
        code=code,
        message=message,
        retryable=retryable,
        details=dict(details or {}),
    )


def _require_mapping(data: Any, label: str = "payload") -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ProtocolValidationError(f"{label} must be a JSON object")
    return data


def _require_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ProtocolValidationError(f"{key} must be a string")
    stripped = value.strip()
    if not stripped:
        raise ProtocolValidationError(f"{key} must be a non-empty string")
    return stripped


def _optional_str(data: dict[str, Any], key: str) -> str | None:
    if key not in data:
        return None
    value = data[key]
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProtocolValidationError(f"{key} must be a string")
    stripped = value.strip()
    return stripped or None


def _optional_int(data: dict[str, Any], key: str) -> int | None:
    if key not in data:
        return None
    value = data[key]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolValidationError(f"{key} must be an integer")
    return value


def _optional_float(data: dict[str, Any], key: str) -> float | None:
    if key not in data:
        return None
    value = data[key]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolValidationError(f"{key} must be a number")
    return float(value)


def _optional_bool(data: dict[str, Any], key: str, *, default: bool = False) -> bool:
    if key not in data:
        return default
    value = data[key]
    if not isinstance(value, bool):
        raise ProtocolValidationError(f"{key} must be a boolean")
    return value


def _optional_object(data: dict[str, Any], key: str) -> dict[str, Any]:
    if key not in data:
        return {}
    value = data[key]
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProtocolValidationError(f"{key} must be an object")
    return dict(value)


def _optional_string_list(data: dict[str, Any], key: str) -> tuple[str, ...]:
    if key not in data:
        return ()
    value = data[key]
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ProtocolValidationError(f"{key} must be an array of strings")
    items: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ProtocolValidationError(f"{key}[{index}] must be a non-empty string")
        items.append(item.strip())
    return tuple(items)


def _parse_initialize_params(data: dict[str, Any]) -> InitializeParams:
    db_path = _require_str(data, "db_path")
    config = _optional_object(data, "config")
    client_capabilities = _optional_string_list(data, "client_capabilities")
    return InitializeParams(
        db_path=db_path,
        config=config,
        client_capabilities=client_capabilities,
    )


def _parse_health_params(data: dict[str, Any]) -> HealthParams:
    return HealthParams(deep=_optional_bool(data, "deep"))


def _parse_search_params(data: dict[str, Any]) -> SearchParams:
    query = _optional_str(data, "query")
    if query is None:
        raise ProtocolValidationError("search requires a non-empty query")
    top_k = _optional_int(data, "top_k")
    if top_k is not None and top_k < 1:
        raise ProtocolValidationError("top_k must be >= 1")
    max_context_chars = _optional_int(data, "max_context_chars")
    if max_context_chars is not None and max_context_chars < 1:
        raise ProtocolValidationError("max_context_chars must be >= 1")
    return SearchParams(
        query=query,
        top_k=top_k,
        session_id=_optional_str(data, "session_id"),
        max_context_chars=max_context_chars,
    )


def _parse_remember_params(data: dict[str, Any]) -> RememberParams:
    content = _optional_str(data, "content")
    if content is None:
        raise ProtocolValidationError("remember requires non-empty content")
    return RememberParams(
        content=content,
        event_type=_optional_str(data, "event_type"),
        importance=_optional_float(data, "importance"),
        metadata=_optional_object(data, "metadata"),
        session_id=_optional_str(data, "session_id"),
    )


def _parse_forget_params(data: dict[str, Any]) -> ForgetParams:
    memory_ids = _optional_string_list(data, "memory_ids")
    query = _optional_str(data, "query")
    if not memory_ids and query is None:
        raise ProtocolValidationError("forget requires memory_ids or query")
    return ForgetParams(memory_ids=memory_ids, query=query)


def _parse_record_turn_params(data: dict[str, Any]) -> RecordTurnParams:
    user_message = _optional_str(data, "user_message") or ""
    agent_message = _optional_str(data, "agent_message") or ""
    if not user_message and not agent_message:
        raise ProtocolValidationError(
            "record_turn requires at least one non-empty user_message or agent_message"
        )
    return RecordTurnParams(
        user_message=user_message,
        agent_message=agent_message,
        session_id=_optional_str(data, "session_id"),
    )


def _parse_consolidate_params(data: dict[str, Any]) -> ConsolidateParams:
    return ConsolidateParams(
        force=_optional_bool(data, "force"),
        session_id=_optional_str(data, "session_id"),
    )


def _parse_params(operation: SidecarOperation, data: dict[str, Any]) -> SidecarParams:
    params = _require_mapping(data.get("params", {}), "params")
    if operation is SidecarOperation.INITIALIZE:
        return _parse_initialize_params(params)
    if operation is SidecarOperation.HEALTH:
        return _parse_health_params(params)
    if operation is SidecarOperation.SEARCH:
        return _parse_search_params(params)
    if operation is SidecarOperation.REMEMBER:
        return _parse_remember_params(params)
    if operation is SidecarOperation.FORGET:
        return _parse_forget_params(params)
    if operation is SidecarOperation.RECORD_TURN:
        return _parse_record_turn_params(params)
    if operation is SidecarOperation.CONSOLIDATE:
        return _parse_consolidate_params(params)
    if operation is SidecarOperation.SHUTDOWN:
        return {}
    raise ProtocolValidationError(f"Unsupported operation {operation.value!r}")


def parse_sidecar_request(data: dict[str, Any]) -> SidecarRequest:
    """Parse and validate a sidecar request envelope."""
    payload = _require_mapping(data)
    protocol_version = _require_str(payload, "protocol_version")
    validate_protocol_version(protocol_version)
    correlation_id = _require_str(payload, "correlation_id")
    operation = validate_operation(payload["operation"])
    timeout_ms = _optional_int(payload, "timeout_ms")
    if timeout_ms is not None and timeout_ms < 1:
        raise ProtocolValidationError("timeout_ms must be >= 1")
    params = _parse_params(operation, payload)
    return SidecarRequest(
        protocol_version=protocol_version,
        correlation_id=correlation_id,
        operation=operation,
        params=params,
        timeout_ms=timeout_ms,
    )


def parse_sidecar_request_line(line: str) -> SidecarRequest:
    """Parse one JSONL request line."""
    stripped = line.strip()
    if not stripped:
        raise ProtocolValidationError("request line must not be empty")
    return parse_sidecar_request(json.loads(stripped))


def _parse_error(data: Any) -> SidecarError | None:
    if data is None:
        return None
    payload = _require_mapping(data, "error")
    code = _require_str(payload, "code")
    message = _require_str(payload, "message")
    if "retryable" not in payload or not isinstance(payload["retryable"], bool):
        raise ProtocolValidationError("error.retryable must be a boolean")
    details = _optional_object(payload, "details")
    return SidecarError(code=code, message=message, retryable=payload["retryable"], details=details)


def _parse_telemetry(data: Any) -> SidecarTelemetry | None:
    if data is None:
        return None
    payload = _require_mapping(data, "telemetry")
    return SidecarTelemetry(
        query_latency_ms=_optional_float(payload, "query_latency_ms"),
        hit_count=_optional_int(payload, "hit_count"),
        returned_characters=_optional_int(payload, "returned_characters"),
        returned_tokens=_optional_int(payload, "returned_tokens"),
        storage_latency_ms=_optional_float(payload, "storage_latency_ms"),
    )


def _parse_search_hit(data: dict[str, Any]) -> SearchHit:
    return SearchHit(
        memory_id=_require_str(data, "memory_id"),
        layer=_optional_int(data, "layer") or 0,
        content=data.get("content", ""),
        score=float(data.get("score", 0.0)),
        retention=float(data.get("retention", 0.0)),
    )


def _parse_result(operation: SidecarOperation, data: dict[str, Any]) -> SidecarResult:
    result = _require_mapping(data.get("result", {}), "result")
    if operation is SidecarOperation.INITIALIZE:
        return InitializeResult(
            ready=bool(result.get("ready", False)),
            negotiated_protocol_version=_require_str(result, "negotiated_protocol_version"),
            server_capabilities=_optional_string_list(result, "server_capabilities"),
            negotiated_capabilities=_optional_string_list(result, "negotiated_capabilities"),
            db_path=_require_str(result, "db_path"),
        )
    if operation is SidecarOperation.HEALTH:
        return HealthResult(
            status=_require_str(result, "status"),
            db_reachable=bool(result.get("db_reachable", False)),
            stats=_optional_object(result, "stats"),
        )
    if operation is SidecarOperation.SEARCH:
        hits_raw = result.get("hits", [])
        if not isinstance(hits_raw, list):
            raise ProtocolValidationError("result.hits must be an array")
        hits = tuple(_parse_search_hit(_require_mapping(item, "hit")) for item in hits_raw)
        return SearchResult(
            context=str(result.get("context", "")),
            hits=hits,
            result_count=int(result.get("result_count", len(hits))),
            truncated=bool(result.get("truncated", False)),
        )
    if operation is SidecarOperation.REMEMBER:
        memory_id = result.get("memory_id")
        if memory_id is not None and not isinstance(memory_id, str):
            raise ProtocolValidationError("result.memory_id must be a string or null")
        return RememberResult(
            memory_id=memory_id,
            recorded=bool(result.get("recorded", False)),
        )
    if operation is SidecarOperation.FORGET:
        return ForgetResult(
            forgotten_count=int(result.get("forgotten_count", 0)),
            memory_ids=_optional_string_list(result, "memory_ids"),
        )
    if operation is SidecarOperation.RECORD_TURN:
        return RecordTurnResult(
            memory_ids=_optional_string_list(result, "memory_ids"),
            recorded_count=int(result.get("recorded_count", 0)),
        )
    if operation is SidecarOperation.CONSOLIDATE:
        return ConsolidateResult(
            extracted_semantics=int(result.get("extracted_semantics", 0)),
            merged_duplicates=int(result.get("merged_duplicates", 0)),
            scheduled_reviews=int(result.get("scheduled_reviews", 0)),
            archived_to_l4=int(result.get("archived_to_l4", 0)),
        )
    if operation is SidecarOperation.SHUTDOWN:
        return ShutdownResult(shutdown_ack=bool(result.get("shutdown_ack", False)))
    raise ProtocolValidationError(f"Unsupported operation {operation.value!r}")


def parse_sidecar_response(data: dict[str, Any]) -> SidecarResponse:
    """Parse and validate a sidecar response envelope."""
    payload = _require_mapping(data)
    protocol_version = _require_str(payload, "protocol_version")
    validate_protocol_version(protocol_version)
    correlation_id = _require_str(payload, "correlation_id")
    operation = validate_operation(payload["operation"])
    if "ok" not in payload or not isinstance(payload["ok"], bool):
        raise ProtocolValidationError("ok must be a boolean")
    result = _parse_result(operation, payload)
    error = _parse_error(payload.get("error"))
    telemetry = _parse_telemetry(payload.get("telemetry"))
    return SidecarResponse(
        protocol_version=protocol_version,
        correlation_id=correlation_id,
        operation=operation,
        ok=payload["ok"],
        result=result,
        error=error,
        telemetry=telemetry,
    )


def parse_sidecar_response_line(line: str) -> SidecarResponse:
    """Parse one JSONL response line."""
    stripped = line.strip()
    if not stripped:
        raise ProtocolValidationError("response line must not be empty")
    return parse_sidecar_response(json.loads(stripped))


def _dataclass_to_json(value: Any, *, omit_none: bool = True) -> Any:
    if isinstance(value, Enum):
        return value.value
    if dataclasses_is_instance(value):
        payload: dict[str, Any] = {}
        for key, item in asdict(value).items():
            if omit_none and item is None:
                continue
            if omit_none and item == {}:
                continue
            if omit_none and item == ():
                continue
            if omit_none and item is False and key in {"deep", "force"}:
                continue
            if omit_none and item == "" and key in {"user_message", "agent_message"}:
                continue
            payload[key] = _dataclass_to_json(item, omit_none=omit_none)
        return payload
    if isinstance(value, tuple):
        return [_dataclass_to_json(item, omit_none=omit_none) for item in value]
    if isinstance(value, list):
        return [_dataclass_to_json(item, omit_none=omit_none) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if omit_none and item is None:
                continue
            result[key] = _dataclass_to_json(item, omit_none=omit_none)
        return result
    return value


def dataclasses_is_instance(value: Any) -> bool:
    return hasattr(value, "__dataclass_fields__")


def _serialize_search_result(result: SearchResult) -> dict[str, Any]:
    return {
        "context": result.context,
        "hits": [
            {
                "memory_id": hit.memory_id,
                "layer": hit.layer,
                "content": hit.content,
                "score": hit.score,
                "retention": hit.retention,
            }
            for hit in result.hits
        ],
        "result_count": result.result_count,
        "truncated": result.truncated,
    }


def _serialize_result_value(operation: SidecarOperation, result: SidecarResult) -> dict[str, Any]:
    if operation is SidecarOperation.INITIALIZE and isinstance(result, InitializeResult):
        return {
            "ready": result.ready,
            "negotiated_protocol_version": result.negotiated_protocol_version,
            "server_capabilities": list(result.server_capabilities),
            "negotiated_capabilities": list(result.negotiated_capabilities),
            "db_path": result.db_path,
        }
    if operation is SidecarOperation.HEALTH and isinstance(result, HealthResult):
        payload = {
            "status": result.status,
            "db_reachable": result.db_reachable,
        }
        if result.stats:
            payload["stats"] = result.stats
        return payload
    if operation is SidecarOperation.SEARCH and isinstance(result, SearchResult):
        return _serialize_search_result(result)
    if operation is SidecarOperation.REMEMBER and isinstance(result, RememberResult):
        return {
            "memory_id": result.memory_id,
            "recorded": result.recorded,
        }
    if operation is SidecarOperation.FORGET and isinstance(result, ForgetResult):
        return {
            "forgotten_count": result.forgotten_count,
            "memory_ids": list(result.memory_ids),
        }
    if operation is SidecarOperation.RECORD_TURN and isinstance(result, RecordTurnResult):
        return {
            "memory_ids": list(result.memory_ids),
            "recorded_count": result.recorded_count,
        }
    if operation is SidecarOperation.CONSOLIDATE and isinstance(result, ConsolidateResult):
        return {
            "extracted_semantics": result.extracted_semantics,
            "merged_duplicates": result.merged_duplicates,
            "scheduled_reviews": result.scheduled_reviews,
            "archived_to_l4": result.archived_to_l4,
        }
    if operation is SidecarOperation.SHUTDOWN and isinstance(result, ShutdownResult):
        return {"shutdown_ack": result.shutdown_ack}
    return _dataclass_to_json(result)


def _serialize_params_value(operation: SidecarOperation, params: SidecarParams) -> dict[str, Any]:
    if operation is SidecarOperation.SHUTDOWN:
        return {}
    if isinstance(params, InitializeParams):
        payload: dict[str, Any] = {"db_path": params.db_path}
        if params.config:
            payload["config"] = params.config
        if params.client_capabilities:
            payload["client_capabilities"] = list(params.client_capabilities)
        return payload
    if isinstance(params, HealthParams):
        return {"deep": params.deep} if params.deep else {}
    if isinstance(params, SearchParams):
        payload = {"query": params.query}
        if params.top_k is not None:
            payload["top_k"] = params.top_k
        if params.session_id is not None:
            payload["session_id"] = params.session_id
        if params.max_context_chars is not None:
            payload["max_context_chars"] = params.max_context_chars
        return payload
    if isinstance(params, RememberParams):
        payload = {"content": params.content}
        if params.event_type is not None:
            payload["event_type"] = params.event_type
        if params.importance is not None:
            payload["importance"] = params.importance
        if params.metadata:
            payload["metadata"] = params.metadata
        if params.session_id is not None:
            payload["session_id"] = params.session_id
        return payload
    if isinstance(params, ForgetParams):
        payload: dict[str, Any] = {}
        if params.memory_ids:
            payload["memory_ids"] = list(params.memory_ids)
        if params.query is not None:
            payload["query"] = params.query
        return payload
    if isinstance(params, RecordTurnParams):
        payload: dict[str, Any] = {}
        if params.user_message:
            payload["user_message"] = params.user_message
        if params.agent_message:
            payload["agent_message"] = params.agent_message
        if params.session_id is not None:
            payload["session_id"] = params.session_id
        return payload
    if isinstance(params, ConsolidateParams):
        payload: dict[str, Any] = {"force": params.force}
        if params.session_id is not None:
            payload["session_id"] = params.session_id
        return payload
    return _dataclass_to_json(params)
def serialize_sidecar_request(request: SidecarRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "protocol_version": request.protocol_version,
        "correlation_id": request.correlation_id,
        "operation": request.operation.value,
        "params": _serialize_params_value(request.operation, request.params),
    }
    if request.timeout_ms is not None:
        payload["timeout_ms"] = request.timeout_ms
    return payload


def serialize_sidecar_response(response: SidecarResponse) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "protocol_version": response.protocol_version,
        "correlation_id": response.correlation_id,
        "operation": response.operation.value,
        "ok": response.ok,
        "result": _serialize_result_value(response.operation, response.result),
        "error": _dataclass_to_json(response.error) if response.error else None,
    }
    if response.telemetry is not None:
        telemetry = {
            key: value
            for key, value in asdict(response.telemetry).items()
            if value is not None
        }
        payload["telemetry"] = telemetry or None
    else:
        payload["telemetry"] = None
    return payload


def serialize_sidecar_request_line(request: SidecarRequest) -> str:
    return json.dumps(serialize_sidecar_request(request), ensure_ascii=False)


def serialize_sidecar_response_line(response: SidecarResponse) -> str:
    return json.dumps(serialize_sidecar_response(response), ensure_ascii=False)


def fail_open_search(
    correlation_id: str,
    error: str,
    *,
    protocol_version: str = CURRENT_PROTOCOL_VERSION,
    code: str = "STORAGE_ERROR",
    retryable: bool = True,
    telemetry: SidecarTelemetry | None = None,
) -> SidecarResponse:
    """Return a fail-open search response that does not block the host agent."""
    return SidecarResponse(
        protocol_version=protocol_version,
        correlation_id=correlation_id,
        operation=SidecarOperation.SEARCH,
        ok=False,
        result=SearchResult(context="", hits=(), result_count=0, truncated=False),
        telemetry=telemetry
        or SidecarTelemetry(
            query_latency_ms=0.0,
            hit_count=0,
            returned_characters=0,
            returned_tokens=0,
        ),
        error=structured_error(code, error, retryable=retryable),
    )


def fail_open_remember(
    correlation_id: str,
    error: str,
    *,
    protocol_version: str = CURRENT_PROTOCOL_VERSION,
    code: str = "STORAGE_ERROR",
    retryable: bool = True,
    telemetry: SidecarTelemetry | None = None,
) -> SidecarResponse:
    """Return a fail-open remember response that does not block the host agent."""
    return SidecarResponse(
        protocol_version=protocol_version,
        correlation_id=correlation_id,
        operation=SidecarOperation.REMEMBER,
        ok=False,
        result=RememberResult(memory_id=None, recorded=False),
        telemetry=telemetry or SidecarTelemetry(storage_latency_ms=0.0),
        error=structured_error(code, error, retryable=retryable),
    )


def fail_open_record_turn(
    correlation_id: str,
    error: str,
    *,
    protocol_version: str = CURRENT_PROTOCOL_VERSION,
    code: str = "STORAGE_ERROR",
    retryable: bool = True,
    telemetry: SidecarTelemetry | None = None,
) -> SidecarResponse:
    """Return a fail-open record_turn response that does not block the host agent."""
    return SidecarResponse(
        protocol_version=protocol_version,
        correlation_id=correlation_id,
        operation=SidecarOperation.RECORD_TURN,
        ok=False,
        result=RecordTurnResult(memory_ids=(), recorded_count=0),
        telemetry=telemetry or SidecarTelemetry(storage_latency_ms=0.0),
        error=structured_error(code, error, retryable=retryable),
    )
