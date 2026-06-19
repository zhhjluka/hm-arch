"""Persistent JSONL stdio sidecar server for OpenClaw and other plugin hosts."""

from __future__ import annotations

import dataclasses
import json
import signal
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from contextlib import contextmanager
from dataclasses import dataclass, field
from queue import Empty, Queue
from datetime import datetime
from typing import Any, Iterator, TextIO

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
    FAIL_OPEN_OPERATIONS,
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
    SidecarOperation,
    SidecarRequest,
    SidecarResponse,
    SidecarTelemetry,
    fail_open_record_turn,
    fail_open_remember,
    fail_open_search,
    negotiate_capabilities,
    negotiate_protocol_version,
    parse_sidecar_request_line,
    serialize_sidecar_response_line,
    structured_error,
)
from hm_arch.types import MemoryStats

_WRITE_OPERATIONS = frozenset(
    {
        SidecarOperation.INITIALIZE,
        SidecarOperation.REMEMBER,
        SidecarOperation.FORGET,
        SidecarOperation.RECORD_TURN,
        SidecarOperation.CONSOLIDATE,
        SidecarOperation.SHUTDOWN,
    }
)

_MUTATING_WRITE_OPERATIONS = frozenset(
    {
        SidecarOperation.REMEMBER,
        SidecarOperation.FORGET,
        SidecarOperation.RECORD_TURN,
        SidecarOperation.CONSOLIDATE,
    }
)


@dataclass
class _InflightWrite:
    cancel: threading.Event
    thread: threading.Thread


class _MemoryAccessLock:
    """Serialize access to a single in-process :class:`~hm_arch.core.HMArch` instance."""

    def __init__(self) -> None:
        self._lock = threading.RLock()

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        with self._lock:
            yield


@dataclass
class SidecarServer:
    """In-process HM-Arch sidecar request dispatcher."""

    memory: HMArch | None = None
    negotiated_protocol_version: str = CURRENT_PROTOCOL_VERSION
    negotiated_capabilities: tuple[str, ...] = ()
    db_path: str | None = None
    recall_top_k: int = 5
    max_context_chars: int = 8000
    _memory_config: MemoryConfig | None = field(default=None, repr=False)
    _memory_lock: _MemoryAccessLock = field(default_factory=_MemoryAccessLock, repr=False)
    _write_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _inflight_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _inflight_write: _InflightWrite | None = field(default=None, repr=False)
    _memory_poisoned: bool = field(default=False, repr=False)
    _shutdown_requested: bool = field(default=False, repr=False)
    _read_executor: ThreadPoolExecutor = field(
        default_factory=lambda: ThreadPoolExecutor(max_workers=4, thread_name_prefix="hm-arch-sidecar"),
        repr=False,
    )

    def close(self) -> None:
        self._abandon_inflight_write()
        self._read_executor.shutdown(wait=False, cancel_futures=True)
        self._close_memory()

    def handle_line(self, line: str) -> str:
        """Parse one JSONL request line and return a serialized response line."""
        try:
            request = parse_sidecar_request_line(line)
        except (ProtocolValidationError, json.JSONDecodeError) as exc:
            return self._serialize_parse_error(line, exc)
        response = self.handle_request(request)
        return serialize_sidecar_response_line(response)

    def handle_request(self, request: SidecarRequest) -> SidecarResponse:
        """Dispatch one sidecar request with optional timeout enforcement."""
        self._reset_memory_if_poisoned()
        timeout_s = None
        if request.timeout_ms is not None:
            timeout_s = request.timeout_ms / 1000.0

        if request.operation in _WRITE_OPERATIONS:
            return self._execute_write(request, timeout_s)

        if timeout_s is None:
            with self._memory_lock.exclusive():
                return self._dispatch_request(request)

        future: Future[SidecarResponse] = self._read_executor.submit(
            self._execute_read,
            request,
        )
        try:
            return future.result(timeout=timeout_s)
        except FuturesTimeoutError:
            future.cancel()
            return self._timeout_response(request)
        except Exception as exc:  # noqa: BLE001 — isolate per-request failures
            return self._internal_error_response(request, exc)

    def _execute_read(self, request: SidecarRequest) -> SidecarResponse:
        with self._memory_lock.exclusive():
            return self._dispatch_request(request)

    def _execute_write(
        self,
        request: SidecarRequest,
        timeout_s: float | None,
    ) -> SidecarResponse:
        if timeout_s is None:
            with self._write_lock:
                with self._memory_lock.exclusive():
                    return self._dispatch_request(request)
        return self._execute_write_with_timeout(request, timeout_s)

    def _execute_write_with_timeout(
        self,
        request: SidecarRequest,
        timeout_s: float,
    ) -> SidecarResponse:
        cancel = threading.Event()
        result_queue: Queue[SidecarResponse | Exception | None] = Queue(maxsize=1)

        def worker() -> None:
            try:
                with self._write_lock:
                    if cancel.is_set():
                        return
                    with self._memory_lock.exclusive():
                        if cancel.is_set():
                            return
                        response = self._dispatch_request(request)
                        if cancel.is_set():
                            self._rollback_timed_out_write(request, response)
                            return
                        result_queue.put(response)
            except Exception as exc:  # noqa: BLE001
                if not cancel.is_set():
                    result_queue.put(exc)
            finally:
                with self._inflight_lock:
                    if self._inflight_write is not None and self._inflight_write.cancel is cancel:
                        self._inflight_write = None

        with self._inflight_lock:
            self._abandon_inflight_write_unlocked()
            thread = threading.Thread(
                target=worker,
                name="hm-arch-sidecar-write",
                daemon=True,
            )
            self._inflight_write = _InflightWrite(cancel=cancel, thread=thread)
            thread.start()

        try:
            item = result_queue.get(timeout=timeout_s)
        except Empty:
            cancel.set()
            self._recover_after_abandoned_write()
            return self._timeout_response(request)

        if item is None:
            return self._timeout_response(request)
        if isinstance(item, Exception):
            return self._internal_error_response(request, item)
        return item

    def _dispatch_request(self, request: SidecarRequest) -> SidecarResponse:
        if request.operation is SidecarOperation.INITIALIZE:
            return self._handle_initialize(request)
        if request.operation is SidecarOperation.SHUTDOWN:
            return self._handle_shutdown(request)
        if self.memory is None:
            return self._not_initialized_response(request)
        return self._route_operation(request)

    def _route_operation(self, request: SidecarRequest) -> SidecarResponse:
        if request.operation is SidecarOperation.HEALTH:
            return self._handle_health(request)
        if request.operation is SidecarOperation.SEARCH:
            return self._handle_search(request)
        if request.operation is SidecarOperation.REMEMBER:
            return self._handle_remember(request)
        if request.operation is SidecarOperation.FORGET:
            return self._handle_forget(request)
        if request.operation is SidecarOperation.RECORD_TURN:
            return self._handle_record_turn(request)
        if request.operation is SidecarOperation.CONSOLIDATE:
            return self._handle_consolidate(request)
        return self._unsupported_operation_response(request)

    def _handle_initialize(self, request: SidecarRequest) -> SidecarResponse:
        assert isinstance(request.params, InitializeParams)
        params = request.params
        previous_config = self._memory_config
        try:
            negotiated = negotiate_protocol_version(request.protocol_version)
            server_caps, negotiated_caps = negotiate_capabilities(
                list(params.client_capabilities)
            )
            memory_config = _memory_config_from_initialize(params)
            self._close_memory()
            self.memory = HMArch(config=memory_config)
            self._memory_config = memory_config
            self.negotiated_protocol_version = negotiated
            self.negotiated_capabilities = negotiated_caps
            self.db_path = params.db_path
            raw_top_k = params.config.get("top_k") or params.config.get("topK")
            if isinstance(raw_top_k, int) and raw_top_k >= 1:
                self.recall_top_k = raw_top_k
            raw_max_chars = params.config.get("max_context_chars") or params.config.get(
                "maxContextChars"
            )
            if isinstance(raw_max_chars, int) and raw_max_chars >= 1:
                self.max_context_chars = raw_max_chars
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
            self._close_memory()
            self._memory_config = previous_config
            self._reopen_memory_if_configured()
            return self._error_response(
                request,
                code="UNSUPPORTED_VERSION",
                message=str(exc),
                retryable=False,
            )
        except Exception as exc:  # noqa: BLE001
            self._close_memory()
            self._memory_config = previous_config
            self._reopen_memory_if_configured()
            return self._error_response(
                request,
                code="STORAGE_ERROR",
                message=str(exc),
                retryable=True,
            )

    def _handle_health(self, request: SidecarRequest) -> SidecarResponse:
        assert isinstance(request.params, HealthParams)
        deep = request.params.deep
        memory = self.memory
        assert memory is not None
        try:
            stats_payload: dict[str, Any] = {}
            status = "healthy"
            db_reachable = True
            if deep:
                stats_payload = _stats_to_dict(memory.get_stats())
            return SidecarResponse(
                protocol_version=self.negotiated_protocol_version,
                correlation_id=request.correlation_id,
                operation=SidecarOperation.HEALTH,
                ok=True,
                result=HealthResult(
                    status=status,
                    db_reachable=db_reachable,
                    stats=stats_payload,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return self._error_response(
                request,
                code="STORAGE_ERROR",
                message=str(exc),
                retryable=True,
            )

    def _handle_search(self, request: SidecarRequest) -> SidecarResponse:
        assert isinstance(request.params, SearchParams)
        params = request.params
        memory = self.memory
        assert memory is not None
        started = time.perf_counter()
        try:
            top_k = params.top_k if params.top_k is not None else self.recall_top_k
            hits = memory.search(params.query, top_k=top_k)
            context, truncated = apply_recall_context_limits(
                build_turn_start_context(
                    memory,
                    params.query,
                    top_k=top_k,
                    hits=hits,
                ),
                params.max_context_chars or self.max_context_chars,
            )
            search_hits = tuple(
                SearchHit(
                    memory_id=item.memory_id,
                    layer=item.layer,
                    content=item.content,
                    score=item.score,
                    retention=item.retention,
                )
                for item in hits.results
            )
            latency_ms = (time.perf_counter() - started) * 1000.0
            telemetry = SidecarTelemetry(
                query_latency_ms=latency_ms,
                hit_count=len(search_hits),
                returned_characters=len(context),
                returned_tokens=_approximate_token_count(context),
            )
            return SidecarResponse(
                protocol_version=self.negotiated_protocol_version,
                correlation_id=request.correlation_id,
                operation=SidecarOperation.SEARCH,
                ok=True,
                result=SearchResult(
                    context=context,
                    hits=search_hits,
                    result_count=len(search_hits),
                    truncated=truncated,
                ),
                telemetry=telemetry,
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = (time.perf_counter() - started) * 1000.0
            return fail_open_search(
                request.correlation_id,
                str(exc),
                protocol_version=self.negotiated_protocol_version,
                telemetry=SidecarTelemetry(
                    query_latency_ms=latency_ms,
                    hit_count=0,
                    returned_characters=0,
                    returned_tokens=0,
                ),
            )

    def _handle_remember(self, request: SidecarRequest) -> SidecarResponse:
        assert isinstance(request.params, RememberParams)
        params = request.params
        memory = self.memory
        assert memory is not None
        started = time.perf_counter()
        try:
            receipt = memory.add(
                params.content,
                event_type=_parse_event_type(params.event_type),
                metadata=dict(params.metadata),
                importance=params.importance,
                session=params.session_id,
            )
            latency_ms = (time.perf_counter() - started) * 1000.0
            return SidecarResponse(
                protocol_version=self.negotiated_protocol_version,
                correlation_id=request.correlation_id,
                operation=SidecarOperation.REMEMBER,
                ok=True,
                result=RememberResult(memory_id=receipt.memory_id, recorded=True),
                telemetry=SidecarTelemetry(storage_latency_ms=latency_ms),
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = (time.perf_counter() - started) * 1000.0
            return fail_open_remember(
                request.correlation_id,
                str(exc),
                protocol_version=self.negotiated_protocol_version,
                telemetry=SidecarTelemetry(storage_latency_ms=latency_ms),
            )

    def _handle_record_turn(self, request: SidecarRequest) -> SidecarResponse:
        assert isinstance(request.params, RecordTurnParams)
        params = request.params
        memory = self.memory
        assert memory is not None
        started = time.perf_counter()
        try:
            memory_ids = record_turn_end(
                memory,
                params.user_message,
                params.agent_message,
            )
            latency_ms = (time.perf_counter() - started) * 1000.0
            return SidecarResponse(
                protocol_version=self.negotiated_protocol_version,
                correlation_id=request.correlation_id,
                operation=SidecarOperation.RECORD_TURN,
                ok=True,
                result=RecordTurnResult(
                    memory_ids=tuple(memory_ids),
                    recorded_count=len(memory_ids),
                ),
                telemetry=SidecarTelemetry(storage_latency_ms=latency_ms),
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = (time.perf_counter() - started) * 1000.0
            return fail_open_record_turn(
                request.correlation_id,
                str(exc),
                protocol_version=self.negotiated_protocol_version,
                telemetry=SidecarTelemetry(storage_latency_ms=latency_ms),
            )

    def _handle_forget(self, request: SidecarRequest) -> SidecarResponse:
        assert isinstance(request.params, ForgetParams)
        params = request.params
        memory = self.memory
        assert memory is not None
        try:
            forgotten_ids: list[str] = []
            if params.memory_ids:
                for memory_id in params.memory_ids:
                    result = memory.forget(memory_id)
                    if result.forgotten_count > 0 or result.archived_count > 0:
                        forgotten_ids.append(memory_id)
            elif params.query is not None:
                if "forget.by_query.v1" not in self.negotiated_capabilities:
                    return self._error_response(
                        request,
                        code="VALIDATION_ERROR",
                        message="forget by query requires forget.by_query.v1 capability",
                        retryable=False,
                    )
                hits = memory.search(params.query, top_k=100)
                for item in hits.results:
                    result = memory.forget(item.memory_id)
                    if result.forgotten_count > 0 or result.archived_count > 0:
                        forgotten_ids.append(item.memory_id)
            return SidecarResponse(
                protocol_version=self.negotiated_protocol_version,
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

    def _handle_consolidate(self, request: SidecarRequest) -> SidecarResponse:
        assert isinstance(request.params, ConsolidateParams)
        memory = self.memory
        assert memory is not None
        try:
            report = run_idle_consolidation(memory)
            return SidecarResponse(
                protocol_version=self.negotiated_protocol_version,
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
        self._shutdown_requested = True
        self._abandon_inflight_write()
        self._close_memory()
        self._memory_config = None
        return SidecarResponse(
            protocol_version=self.negotiated_protocol_version,
            correlation_id=request.correlation_id,
            operation=SidecarOperation.SHUTDOWN,
            ok=True,
            result=ShutdownResult(shutdown_ack=True),
        )

    def _serialize_parse_error(self, line: str, exc: Exception) -> str:
        correlation_id = "unknown"
        operation_name = "search"
        protocol_version = CURRENT_PROTOCOL_VERSION
        try:
            payload = json.loads(line.strip())
            if isinstance(payload, dict):
                raw_id = payload.get("correlation_id")
                if isinstance(raw_id, str) and raw_id.strip():
                    correlation_id = raw_id.strip()
                raw_op = payload.get("operation")
                if isinstance(raw_op, str) and raw_op.strip():
                    operation_name = raw_op.strip().lower()
        except json.JSONDecodeError:
            pass

        try:
            operation = SidecarOperation(operation_name)
        except ValueError:
            operation = SidecarOperation.SEARCH

        message = str(exc)
        if operation.value in FAIL_OPEN_OPERATIONS:
            response = self._fail_open_validation_response(
                correlation_id=correlation_id,
                operation=operation,
                message=message,
                protocol_version=protocol_version,
            )
        else:
            response = SidecarResponse(
                protocol_version=protocol_version,
                correlation_id=correlation_id,
                operation=operation,
                ok=False,
                result={},
                error=structured_error(
                    "VALIDATION_ERROR",
                    message,
                    retryable=False,
                ),
            )
        return serialize_sidecar_response_line(response)

    def _fail_open_validation_response(
        self,
        *,
        correlation_id: str,
        operation: SidecarOperation,
        message: str,
        protocol_version: str,
    ) -> SidecarResponse:
        if operation is SidecarOperation.SEARCH:
            return fail_open_search(
                correlation_id,
                message,
                protocol_version=protocol_version,
                code="VALIDATION_ERROR",
                retryable=False,
            )
        if operation is SidecarOperation.REMEMBER:
            return fail_open_remember(
                correlation_id,
                message,
                protocol_version=protocol_version,
                code="VALIDATION_ERROR",
                retryable=False,
            )
        return fail_open_record_turn(
            correlation_id,
            message,
            protocol_version=protocol_version,
            code="VALIDATION_ERROR",
            retryable=False,
        )

    def _not_initialized_response(self, request: SidecarRequest) -> SidecarResponse:
        message = "call initialize before other operations"
        if request.operation is SidecarOperation.SEARCH:
            return fail_open_search(
                request.correlation_id,
                message,
                protocol_version=self.negotiated_protocol_version,
                code="NOT_INITIALIZED",
                retryable=True,
            )
        if request.operation is SidecarOperation.REMEMBER:
            return fail_open_remember(
                request.correlation_id,
                message,
                protocol_version=self.negotiated_protocol_version,
                code="NOT_INITIALIZED",
                retryable=True,
            )
        if request.operation is SidecarOperation.RECORD_TURN:
            return fail_open_record_turn(
                request.correlation_id,
                message,
                protocol_version=self.negotiated_protocol_version,
                code="NOT_INITIALIZED",
                retryable=True,
            )
        return self._error_response(
            request,
            code="NOT_INITIALIZED",
            message=message,
            retryable=True,
        )

    def _timeout_response(self, request: SidecarRequest) -> SidecarResponse:
        if request.operation.value in FAIL_OPEN_OPERATIONS:
            return self._fail_open_storage_error(
                request,
                "operation exceeded timeout_ms",
                code="TIMEOUT",
                retryable=True,
            )
        return self._error_response(
            request,
            code="TIMEOUT",
            message="operation exceeded timeout_ms",
            retryable=True,
        )

    def _unsupported_operation_response(self, request: SidecarRequest) -> SidecarResponse:
        return self._error_response(
            request,
            code="UNSUPPORTED_OPERATION",
            message=f"unsupported operation {request.operation.value!r}",
            retryable=False,
        )

    def _internal_error_response(
        self,
        request: SidecarRequest,
        exc: Exception,
    ) -> SidecarResponse:
        if request.operation.value in FAIL_OPEN_OPERATIONS:
            return self._fail_open_storage_error(request, str(exc))
        return self._error_response(
            request,
            code="INTERNAL_ERROR",
            message=str(exc),
            retryable=True,
        )

    def _fail_open_storage_error(
        self,
        request: SidecarRequest,
        message: str,
        *,
        code: str = "STORAGE_ERROR",
        retryable: bool = True,
    ) -> SidecarResponse:
        if request.operation is SidecarOperation.SEARCH:
            return fail_open_search(
                request.correlation_id,
                message,
                protocol_version=self.negotiated_protocol_version,
                code=code,
                retryable=retryable,
            )
        if request.operation is SidecarOperation.REMEMBER:
            return fail_open_remember(
                request.correlation_id,
                message,
                protocol_version=self.negotiated_protocol_version,
                code=code,
                retryable=retryable,
            )
        return fail_open_record_turn(
            request.correlation_id,
            message,
            protocol_version=self.negotiated_protocol_version,
            code=code,
            retryable=retryable,
        )

    def _error_response(
        self,
        request: SidecarRequest,
        *,
        code: str,
        message: str,
        retryable: bool,
        result: dict[str, Any] | None = None,
    ) -> SidecarResponse:
        return SidecarResponse(
            protocol_version=self.negotiated_protocol_version,
            correlation_id=request.correlation_id,
            operation=request.operation,
            ok=False,
            result=result or {},
            error=structured_error(code, message, retryable=retryable),
        )

    def _close_memory(self) -> None:
        memory = self.memory
        self.memory = None
        if memory is not None:
            try:
                memory.close()
            except Exception:  # noqa: BLE001 — best-effort teardown
                pass

    def _reopen_memory_if_configured(self) -> None:
        if self._memory_config is None or self.memory is not None:
            return
        self.memory = HMArch(config=self._memory_config)

    def _abandon_inflight_write(self) -> None:
        with self._inflight_lock:
            self._abandon_inflight_write_unlocked()

    def _abandon_inflight_write_unlocked(self) -> None:
        inflight = self._inflight_write
        if inflight is None:
            return
        inflight.cancel.set()

    def _recover_after_abandoned_write(self) -> None:
        def recover() -> None:
            inflight: _InflightWrite | None
            with self._inflight_lock:
                inflight = self._inflight_write
            if inflight is None:
                return
            inflight.thread.join(timeout=30.0)
            if inflight.thread.is_alive():
                self._memory_poisoned = True

        threading.Thread(
            target=recover,
            name="hm-arch-sidecar-write-recover",
            daemon=True,
        ).start()

    def _reset_memory_if_poisoned(self) -> None:
        if not self._memory_poisoned:
            return
        acquired = self._write_lock.acquire(timeout=0)
        if not acquired:
            return
        try:
            self._memory_poisoned = False
            self._close_memory()
            self._reopen_memory_if_configured()
        finally:
            self._write_lock.release()

    def _rollback_timed_out_write(
        self,
        request: SidecarRequest,
        response: SidecarResponse,
    ) -> None:
        if request.operation not in _MUTATING_WRITE_OPERATIONS or not response.ok:
            return
        memory = self.memory
        if memory is None:
            return
        try:
            if request.operation is SidecarOperation.REMEMBER:
                assert isinstance(response.result, RememberResult)
                if response.result.memory_id:
                    memory.forget(response.result.memory_id)
            elif request.operation is SidecarOperation.RECORD_TURN:
                assert isinstance(response.result, RecordTurnResult)
                for memory_id in response.result.memory_ids:
                    memory.forget(memory_id)
        except Exception:  # noqa: BLE001 — rollback is best-effort
            pass


def run_stdio_server(
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    server: SidecarServer | None = None,
) -> int:
    """Run the persistent JSONL sidecar loop until stdin closes or shutdown."""
    input_stream = stdin or sys.stdin
    output_stream = stdout or sys.stdout
    sidecar = server or SidecarServer()
    stop = threading.Event()

    def _handle_signal(_signum: int, _frame: object | None) -> None:
        stop.set()

    previous_int = signal.signal(signal.SIGINT, _handle_signal)
    previous_term = signal.signal(signal.SIGTERM, _handle_signal)

    try:
        for raw_line in input_stream:
            if stop.is_set():
                break
            stripped = raw_line.strip()
            if not stripped:
                continue
            response_line = sidecar.handle_line(stripped)
            output_stream.write(response_line)
            output_stream.write("\n")
            output_stream.flush()
            if sidecar._shutdown_requested:
                break
    finally:
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGTERM, previous_term)
        sidecar.close()
    return 0


def _memory_config_from_initialize(params: InitializeParams) -> MemoryConfig:
    raw_config = dict(params.config)
    preset = raw_config.pop("preset", None)
    field_names = {item.name for item in dataclasses.fields(MemoryConfig)}
    overrides = {
        key: value for key, value in raw_config.items() if key in field_names
    }
    if preset is not None:
        base = MemoryConfig.preset(str(preset))
        return dataclasses.replace(base, db_path=params.db_path, **overrides)
    return MemoryConfig(db_path=params.db_path, **overrides)


def _parse_event_type(value: str | None) -> EventType:
    if value is None:
        return EventType.CONVERSATION
    try:
        return EventType(value.lower())
    except ValueError:
        return EventType.CONVERSATION


def _approximate_token_count(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    return len(stripped.split())


def _stats_to_dict(stats: MemoryStats) -> dict[str, Any]:
    last_consolidation = stats.last_consolidation_at
    if isinstance(last_consolidation, datetime):
        last_consolidation_value: str | None = last_consolidation.isoformat()
    else:
        last_consolidation_value = None
    return {
        "total_memories": stats.total_memories,
        "by_layer": dict(stats.by_layer),
        "storage_size_mb": stats.storage_size_mb,
        "retention_distribution": dict(stats.retention_distribution),
        "review_queue_length": stats.review_queue_length,
        "last_consolidation_at": last_consolidation_value,
        "archive_storage_mb": stats.archive_storage_mb,
        "sensitive_data_diagnostics": dict(stats.sensitive_data_diagnostics),
    }
