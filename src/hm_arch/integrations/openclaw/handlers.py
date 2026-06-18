"""Sidecar operation handlers backed by :class:`~hm_arch.HMArch`."""

from __future__ import annotations

import time
from dataclasses import asdict, replace
from typing import Any

from hm_arch import EventType, HMArch
from hm_arch.config import MemoryConfig
from hm_arch.integrations.common import (
    apply_recall_context_limits,
    build_turn_start_context,
    record_turn_end,
    run_idle_consolidation,
)
from hm_arch.integrations.sidecar.protocol import (
    CURRENT_PROTOCOL_VERSION,
    DEFAULT_SERVER_CAPABILITIES,
    ConsolidateParams,
    ConsolidateResult,
    ForgetParams,
    ForgetResult,
    HealthParams,
    HealthResult,
    InitializeParams,
    InitializeResult,
    ProtocolValidationError,
    RecordTurnParams,
    RecordTurnResult,
    RememberParams,
    RememberResult,
    SearchHit,
    SearchParams,
    SearchResult,
    ShutdownResult,
    SidecarError,
    SidecarOperation,
    SidecarRequest,
    SidecarResponse,
    SidecarTelemetry,
    fail_open_record_turn,
    fail_open_remember,
    fail_open_search,
    negotiate_capabilities,
    negotiate_protocol_version,
    structured_error,
)

_DEFAULT_TOP_K = 5
_DEFAULT_MAX_CONTEXT_CHARS = 4000
_FORGET_BY_QUERY_TOP_K = 50


def _parse_event_type(value: str | None) -> EventType:
    if not value:
        return EventType.CONVERSATION
    normalized = value.strip().lower()
    for event_type in EventType:
        if event_type.value == normalized:
            return event_type
    raise ProtocolValidationError(f"unsupported event_type {value!r}")


def _approx_token_count(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    return len(stripped.split())


def _memory_stats_payload(memory: HMArch) -> dict[str, Any]:
    stats = memory.get_stats()
    payload = asdict(stats)
    last = payload.get("last_consolidation_at")
    if last is not None and hasattr(last, "isoformat"):
        payload["last_consolidation_at"] = last.isoformat()
    return payload


def _search_hits_from_items(hits) -> tuple[SearchHit, ...]:
    return tuple(
        SearchHit(
            memory_id=item.memory_id,
            layer=item.layer,
            content=item.content,
            score=float(item.score),
            retention=float(item.retention),
        )
        for item in hits
    )


class SidecarHandlers:
    """Stateful HM-Arch sidecar operation handlers."""

    def __init__(self) -> None:
        self._memory: HMArch | None = None
        self._negotiated_protocol_version = CURRENT_PROTOCOL_VERSION
        self._db_path: str | None = None
        self._top_k = _DEFAULT_TOP_K
        self._max_context_chars = _DEFAULT_MAX_CONTEXT_CHARS

    @property
    def initialized(self) -> bool:
        return self._memory is not None

    def close(self) -> None:
        if self._memory is not None:
            self._memory.close()
            self._memory = None

    def dispatch(self, request: SidecarRequest) -> SidecarResponse:
        operation = request.operation
        if operation is SidecarOperation.INITIALIZE:
            return self._handle_initialize(request)
        if not self.initialized:
            return self._not_initialized_response(request)
        if operation is SidecarOperation.HEALTH:
            return self._handle_health(request)
        if operation is SidecarOperation.SEARCH:
            return self._handle_search(request)
        if operation is SidecarOperation.REMEMBER:
            return self._handle_remember(request)
        if operation is SidecarOperation.FORGET:
            return self._handle_forget(request)
        if operation is SidecarOperation.RECORD_TURN:
            return self._handle_record_turn(request)
        if operation is SidecarOperation.CONSOLIDATE:
            return self._handle_consolidate(request)
        if operation is SidecarOperation.SHUTDOWN:
            return self._handle_shutdown(request)
        return SidecarResponse(
            protocol_version=self._negotiated_protocol_version,
            correlation_id=request.correlation_id,
            operation=operation,
            ok=False,
            result={},
            error=structured_error(
                "UNSUPPORTED_OPERATION",
                f"Unsupported operation {operation.value!r}",
                retryable=False,
            ),
        )

    def _not_initialized_response(self, request: SidecarRequest) -> SidecarResponse:
        error = structured_error(
            "NOT_INITIALIZED",
            "Sidecar is not initialized; call initialize first",
            retryable=True,
        )
        if request.operation is SidecarOperation.SEARCH:
            return fail_open_search(
                request.correlation_id,
                error.message,
                protocol_version=self._negotiated_protocol_version,
                code=error.code,
                retryable=error.retryable,
            )
        if request.operation is SidecarOperation.REMEMBER:
            return fail_open_remember(
                request.correlation_id,
                error.message,
                protocol_version=self._negotiated_protocol_version,
                code=error.code,
                retryable=error.retryable,
            )
        if request.operation is SidecarOperation.RECORD_TURN:
            return fail_open_record_turn(
                request.correlation_id,
                error.message,
                protocol_version=self._negotiated_protocol_version,
                code=error.code,
                retryable=error.retryable,
            )
        return SidecarResponse(
            protocol_version=self._negotiated_protocol_version,
            correlation_id=request.correlation_id,
            operation=request.operation,
            ok=False,
            result={},
            error=error,
        )

    def _handle_initialize(self, request: SidecarRequest) -> SidecarResponse:
        assert isinstance(request.params, InitializeParams)
        params = request.params
        try:
            negotiated = negotiate_protocol_version(request.protocol_version)
            server_caps, negotiated_caps = negotiate_capabilities(
                list(params.client_capabilities),
                server_capabilities=DEFAULT_SERVER_CAPABILITIES,
            )
            self.close()
            config_values = dict(params.config)
            preset = config_values.pop("preset", None)
            plugin_top_k = config_values.pop("topK", None)
            plugin_max_chars = config_values.pop("maxContextChars", None)
            if preset is not None:
                memory_config = replace(
                    MemoryConfig.preset(str(preset)),
                    db_path=params.db_path,
                )
            else:
                memory_config = MemoryConfig(db_path=params.db_path)
            self._top_k = int(plugin_top_k) if plugin_top_k is not None else _DEFAULT_TOP_K
            self._max_context_chars = (
                int(plugin_max_chars)
                if plugin_max_chars is not None
                else _DEFAULT_MAX_CONTEXT_CHARS
            )
            self._memory = HMArch(config=memory_config)
            self._negotiated_protocol_version = negotiated
            self._db_path = params.db_path
            return SidecarResponse(
                protocol_version=negotiated,
                correlation_id=request.correlation_id,
                operation=SidecarOperation.INITIALIZE,
                ok=True,
                result=InitializeResult(
                    ready=True,
                    negotiated_protocol_version=negotiated,
                    server_capabilities=server_caps,
                    negotiated_capabilities=negotiated_caps,
                    db_path=params.db_path,
                ),
            )
        except ProtocolValidationError as exc:
            return self._error_response(
                request,
                code="UNSUPPORTED_VERSION",
                message=str(exc),
                retryable=False,
            )
        except Exception as exc:  # noqa: BLE001
            return self._error_response(
                request,
                code="STORAGE_ERROR",
                message=str(exc),
                retryable=True,
            )

    def _handle_health(self, request: SidecarRequest) -> SidecarResponse:
        assert isinstance(request.params, HealthParams)
        memory = self._require_memory()
        try:
            memory.get_stats()
            stats: dict[str, Any] = {}
            if request.params.deep:
                stats = _memory_stats_payload(memory)
            return SidecarResponse(
                protocol_version=self._negotiated_protocol_version,
                correlation_id=request.correlation_id,
                operation=SidecarOperation.HEALTH,
                ok=True,
                result=HealthResult(
                    status="healthy",
                    db_reachable=True,
                    stats=stats,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return SidecarResponse(
                protocol_version=self._negotiated_protocol_version,
                correlation_id=request.correlation_id,
                operation=SidecarOperation.HEALTH,
                ok=True,
                result=HealthResult(
                    status="unhealthy",
                    db_reachable=False,
                    stats={"error": str(exc)},
                ),
            )

    def _handle_search(self, request: SidecarRequest) -> SidecarResponse:
        assert isinstance(request.params, SearchParams)
        params = request.params
        memory = self._require_memory()
        started = time.perf_counter()
        try:
            top_k = params.top_k or self._top_k
            max_chars = params.max_context_chars or self._max_context_chars
            hits = memory.search(params.query, top_k=top_k)
            context, truncated = apply_recall_context_limits(
                build_turn_start_context(
                    memory,
                    params.query,
                    top_k=top_k,
                    hits=hits,
                ),
                max_chars,
            )
            search_hits = _search_hits_from_items(hits.results)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return SidecarResponse(
                protocol_version=self._negotiated_protocol_version,
                correlation_id=request.correlation_id,
                operation=SidecarOperation.SEARCH,
                ok=True,
                result=SearchResult(
                    context=context,
                    hits=search_hits,
                    result_count=len(search_hits),
                    truncated=truncated,
                ),
                telemetry=SidecarTelemetry(
                    query_latency_ms=elapsed_ms,
                    hit_count=len(search_hits),
                    returned_characters=len(context),
                    returned_tokens=_approx_token_count(context),
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return fail_open_search(
                request.correlation_id,
                str(exc),
                protocol_version=self._negotiated_protocol_version,
            )

    def _handle_remember(self, request: SidecarRequest) -> SidecarResponse:
        assert isinstance(request.params, RememberParams)
        params = request.params
        memory = self._require_memory()
        started = time.perf_counter()
        try:
            event_type = _parse_event_type(params.event_type)
            receipt = memory.add(
                params.content,
                event_type=event_type,
                metadata=dict(params.metadata),
                importance=params.importance,
                session=params.session_id,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return SidecarResponse(
                protocol_version=self._negotiated_protocol_version,
                correlation_id=request.correlation_id,
                operation=SidecarOperation.REMEMBER,
                ok=True,
                result=RememberResult(
                    memory_id=receipt.memory_id,
                    recorded=True,
                ),
                telemetry=SidecarTelemetry(storage_latency_ms=elapsed_ms),
            )
        except ProtocolValidationError as exc:
            return fail_open_remember(
                request.correlation_id,
                str(exc),
                protocol_version=self._negotiated_protocol_version,
                code="VALIDATION_ERROR",
                retryable=False,
            )
        except Exception as exc:  # noqa: BLE001
            return fail_open_remember(
                request.correlation_id,
                str(exc),
                protocol_version=self._negotiated_protocol_version,
            )

    def _handle_forget(self, request: SidecarRequest) -> SidecarResponse:
        assert isinstance(request.params, ForgetParams)
        params = request.params
        memory = self._require_memory()
        try:
            target_ids = list(params.memory_ids)
            if params.query and not target_ids:
                hits = memory.search(params.query, top_k=_FORGET_BY_QUERY_TOP_K)
                target_ids = [item.memory_id for item in hits.results]
            forgotten_ids: list[str] = []
            for memory_id in target_ids:
                result = memory.forget(memory_id)
                if result.forgotten_count > 0:
                    forgotten_ids.append(memory_id)
            return SidecarResponse(
                protocol_version=self._negotiated_protocol_version,
                correlation_id=request.correlation_id,
                operation=SidecarOperation.FORGET,
                ok=True,
                result=ForgetResult(
                    forgotten_count=len(forgotten_ids),
                    memory_ids=tuple(forgotten_ids),
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return self._error_response(
                request,
                code="STORAGE_ERROR",
                message=str(exc),
                retryable=True,
            )

    def _handle_record_turn(self, request: SidecarRequest) -> SidecarResponse:
        assert isinstance(request.params, RecordTurnParams)
        params = request.params
        memory = self._require_memory()
        started = time.perf_counter()
        try:
            memory_ids = record_turn_end(
                memory,
                params.user_message,
                params.agent_message,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return SidecarResponse(
                protocol_version=self._negotiated_protocol_version,
                correlation_id=request.correlation_id,
                operation=SidecarOperation.RECORD_TURN,
                ok=True,
                result=RecordTurnResult(
                    memory_ids=tuple(memory_ids),
                    recorded_count=len(memory_ids),
                ),
                telemetry=SidecarTelemetry(storage_latency_ms=elapsed_ms),
            )
        except Exception as exc:  # noqa: BLE001
            return fail_open_record_turn(
                request.correlation_id,
                str(exc),
                protocol_version=self._negotiated_protocol_version,
            )

    def _handle_consolidate(self, request: SidecarRequest) -> SidecarResponse:
        assert isinstance(request.params, ConsolidateParams)
        memory = self._require_memory()
        try:
            report = run_idle_consolidation(memory)
            return SidecarResponse(
                protocol_version=self._negotiated_protocol_version,
                correlation_id=request.correlation_id,
                operation=SidecarOperation.CONSOLIDATE,
                ok=True,
                result=ConsolidateResult(
                    extracted_semantics=report.extracted_semantics,
                    merged_duplicates=report.merged_duplicates,
                    scheduled_reviews=report.scheduled_reviews,
                    archived_to_l4=report.archived_to_l4,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return self._error_response(
                request,
                code="STORAGE_ERROR",
                message=str(exc),
                retryable=True,
            )

    def _handle_shutdown(self, request: SidecarRequest) -> SidecarResponse:
        self.close()
        return SidecarResponse(
            protocol_version=self._negotiated_protocol_version,
            correlation_id=request.correlation_id,
            operation=SidecarOperation.SHUTDOWN,
            ok=True,
            result=ShutdownResult(shutdown_ack=True),
        )

    def _require_memory(self) -> HMArch:
        if self._memory is None:
            raise RuntimeError("sidecar not initialized")
        return self._memory

    def _error_response(
        self,
        request: SidecarRequest,
        *,
        code: str,
        message: str,
        retryable: bool,
    ) -> SidecarResponse:
        return SidecarResponse(
            protocol_version=self._negotiated_protocol_version,
            correlation_id=request.correlation_id,
            operation=request.operation,
            ok=False,
            result={},
            error=SidecarError(
                code=code,
                message=message,
                retryable=retryable,
            ),
        )
