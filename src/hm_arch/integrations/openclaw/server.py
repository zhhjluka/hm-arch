"""JSONL stdio server for the HM-Arch OpenClaw sidecar."""

from __future__ import annotations

import json
import logging
import signal
import sys
import threading
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import BinaryIO, TextIO

from hm_arch.integrations.sidecar.protocol import (
    CURRENT_PROTOCOL_VERSION,
    ProtocolValidationError,
    SidecarOperation,
    SidecarRequest,
    SidecarResponse,
    parse_sidecar_request,
    serialize_sidecar_response_line,
    structured_error,
)

from .handlers import SidecarHandlers

logger = logging.getLogger(__name__)


class SidecarServer:
    """Long-lived JSONL stdio sidecar process."""

    def __init__(
        self,
        *,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        handlers: SidecarHandlers | None = None,
    ) -> None:
        self._stdin = stdin or sys.stdin
        self._stdout = stdout or sys.stdout
        self._handlers = handlers or SidecarHandlers()
        self._write_lock = threading.Lock()
        self._shutdown_requested = threading.Event()
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="hm-arch-sidecar")

    @property
    def handlers(self) -> SidecarHandlers:
        return self._handlers

    def request_shutdown(self) -> None:
        self._shutdown_requested.set()

    def run(self) -> int:
        """Process requests until stdin closes or shutdown is requested."""
        self._install_signal_handlers()
        try:
            for line in self._stdin:
                if self._shutdown_requested.is_set():
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                response = self._handle_line(stripped)
                self._emit_response(response)
                if (
                    response.operation is SidecarOperation.SHUTDOWN
                    and response.ok
                ):
                    break
        finally:
            self._handlers.close()
            self._executor.shutdown(wait=False, cancel_futures=True)
        return 0

    def _install_signal_handlers(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return

        def _handle_signal(signum: int, _frame: object) -> None:
            logger.info("received signal %s; shutting down sidecar", signum)
            self.request_shutdown()

        for signum in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(signum, _handle_signal)
            except (ValueError, OSError):
                continue

    def _handle_line(self, line: str) -> SidecarResponse:
        try:
            request = parse_sidecar_request(json.loads(line))
        except json.JSONDecodeError as exc:
            return self._validation_error_response(
                correlation_id="unknown",
                operation=SidecarOperation.HEALTH,
                message=f"invalid JSON on stdin: {exc}",
            )
        except ProtocolValidationError as exc:
            return self._validation_error_response(
                correlation_id=_extract_correlation_id(line),
                operation=_extract_operation(line),
                message=str(exc),
            )

        return self._dispatch_with_timeout(request)

    def _dispatch_with_timeout(self, request: SidecarRequest) -> SidecarResponse:
        timeout_s = None
        if request.timeout_ms is not None:
            timeout_s = max(request.timeout_ms, 1) / 1000.0

        def _execute() -> SidecarResponse:
            if request.operation in {
                SidecarOperation.REMEMBER,
                SidecarOperation.RECORD_TURN,
                SidecarOperation.CONSOLIDATE,
                SidecarOperation.FORGET,
                SidecarOperation.INITIALIZE,
                SidecarOperation.SHUTDOWN,
            }:
                with self._write_lock:
                    return self._handlers.dispatch(request)
            return self._handlers.dispatch(request)

        if timeout_s is None:
            return _execute()

        future: Future[SidecarResponse] = self._executor.submit(_execute)
        try:
            return future.result(timeout=timeout_s)
        except FuturesTimeoutError:
            future.cancel()
            return self._timeout_response(request)

    def _emit_response(self, response: SidecarResponse) -> None:
        payload = serialize_sidecar_response_line(response)
        with self._write_lock:
            self._stdout.write(payload + "\n")
            self._stdout.flush()

    def _validation_error_response(
        self,
        *,
        correlation_id: str,
        operation: SidecarOperation,
        message: str,
    ) -> SidecarResponse:
        return SidecarResponse(
            protocol_version=CURRENT_PROTOCOL_VERSION,
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

    def _timeout_response(self, request: SidecarRequest) -> SidecarResponse:
        from hm_arch.integrations.sidecar.protocol import (
            fail_open_record_turn,
            fail_open_remember,
            fail_open_search,
        )

        message = f"operation timed out after {request.timeout_ms}ms"
        if request.operation is SidecarOperation.SEARCH:
            return fail_open_search(
                request.correlation_id,
                message,
                code="TIMEOUT",
                retryable=True,
            )
        if request.operation is SidecarOperation.REMEMBER:
            return fail_open_remember(
                request.correlation_id,
                message,
                code="TIMEOUT",
                retryable=True,
            )
        if request.operation is SidecarOperation.RECORD_TURN:
            return fail_open_record_turn(
                request.correlation_id,
                message,
                code="TIMEOUT",
                retryable=True,
            )
        return SidecarResponse(
            protocol_version=CURRENT_PROTOCOL_VERSION,
            correlation_id=request.correlation_id,
            operation=request.operation,
            ok=False,
            result={},
            error=structured_error("TIMEOUT", message, retryable=True),
        )


def _extract_correlation_id(line: str) -> str:
    try:
        payload = json.loads(line)
        if isinstance(payload, dict):
            value = payload.get("correlation_id")
            if isinstance(value, str) and value.strip():
                return value.strip()
    except json.JSONDecodeError:
        pass
    return "unknown"


def _extract_operation(line: str) -> SidecarOperation:
    try:
        payload = json.loads(line)
        if isinstance(payload, dict):
            value = payload.get("operation")
            if isinstance(value, str):
                return SidecarOperation(value.strip().lower())
    except (json.JSONDecodeError, ValueError):
        pass
    return SidecarOperation.HEALTH


def configure_sidecar_logging(stderr: BinaryIO | TextIO | None = None) -> None:
    """Route sidecar logs to stderr only."""
    stream = stderr or sys.stderr
    logging.basicConfig(
        level=logging.INFO,
        format="hm-arch-sidecar %(levelname)s %(message)s",
        stream=stream,
        force=True,
    )
