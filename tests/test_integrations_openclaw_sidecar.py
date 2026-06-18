"""Offline integration tests for the HM-Arch OpenClaw JSONL sidecar."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from hm_arch.integrations.openclaw.handlers import SidecarHandlers
from hm_arch.integrations.openclaw.server import SidecarServer
from hm_arch.integrations.sidecar.protocol import (
    CURRENT_PROTOCOL_VERSION,
    parse_sidecar_response_line,
    serialize_sidecar_request_line,
)
from hm_arch.integrations.sidecar.protocol import (
    InitializeParams,
    RememberParams,
    SearchParams,
    SidecarOperation,
    SidecarRequest,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _request(
    operation: SidecarOperation,
    params: object,
    *,
    correlation_id: str,
    timeout_ms: int | None = None,
) -> SidecarRequest:
    return SidecarRequest(
        protocol_version=CURRENT_PROTOCOL_VERSION,
        correlation_id=correlation_id,
        operation=operation,
        params=params,
        timeout_ms=timeout_ms,
    )


def _run_session(stdin_lines: list[str]) -> list[dict]:
    server = SidecarServer()
    stdout_lines: list[str] = []

    class _Writer:
        def write(self, text: str) -> int:
            stdout_lines.append(text.rstrip("\n"))
            return len(text)

        def flush(self) -> None:
            return None

    class _Reader:
        def __iter__(self):
            yield from stdin_lines

    server._stdin = _Reader()  # type: ignore[assignment]
    server._stdout = _Writer()  # type: ignore[assignment]
    assert server.run() == 0
    return [json.loads(line) for line in stdout_lines if line.strip()]


def test_sidecar_initialize_search_remember_shutdown(tmp_path: Path) -> None:
    db_path = str(tmp_path / "sidecar.db")
    responses = _run_session(
        [
            serialize_sidecar_request_line(
                _request(
                    SidecarOperation.INITIALIZE,
                    InitializeParams(db_path=db_path, config={"preset": "code_agent"}),
                    correlation_id="init-1",
                )
            ),
            serialize_sidecar_request_line(
                _request(
                    SidecarOperation.REMEMBER,
                    RememberParams(content="offline pytest memory"),
                    correlation_id="remember-1",
                )
            ),
            serialize_sidecar_request_line(
                _request(
                    SidecarOperation.SEARCH,
                    SearchParams(query="offline pytest"),
                    correlation_id="search-1",
                )
            ),
            serialize_sidecar_request_line(
                _request(SidecarOperation.SHUTDOWN, {}, correlation_id="shutdown-1")
            ),
        ]
    )
    assert responses[0]["ok"] is True
    assert responses[1]["ok"] is True
    assert responses[1]["result"]["recorded"] is True
    assert responses[2]["ok"] is True
    assert responses[2]["result"]["result_count"] >= 1
    assert "offline pytest memory" in responses[2]["result"]["context"]
    assert responses[2]["telemetry"]["query_latency_ms"] >= 0
    assert responses[3]["ok"] is True


def test_sidecar_store_restart_recall(tmp_path: Path) -> None:
    db_path = str(tmp_path / "persist.db")

    def _session() -> list[dict]:
        return _run_session(
            [
                serialize_sidecar_request_line(
                    _request(
                        SidecarOperation.INITIALIZE,
                        InitializeParams(db_path=db_path),
                        correlation_id="init",
                    )
                ),
                serialize_sidecar_request_line(
                    _request(
                        SidecarOperation.REMEMBER,
                        RememberParams(content="persistent recall marker"),
                        correlation_id="remember",
                    )
                ),
                serialize_sidecar_request_line(
                    _request(SidecarOperation.SHUTDOWN, {}, correlation_id="shutdown")
                ),
            ]
        )

    first = _session()
    assert first[1]["ok"] is True

    second = _run_session(
        [
            serialize_sidecar_request_line(
                _request(
                    SidecarOperation.INITIALIZE,
                    InitializeParams(db_path=db_path),
                    correlation_id="init-2",
                )
            ),
            serialize_sidecar_request_line(
                _request(
                    SidecarOperation.SEARCH,
                    SearchParams(query="persistent recall marker"),
                    correlation_id="search-2",
                )
            ),
            serialize_sidecar_request_line(
                _request(SidecarOperation.SHUTDOWN, {}, correlation_id="shutdown-2")
            ),
        ]
    )
    assert second[1]["ok"] is True
    assert second[1]["result"]["result_count"] >= 1
    assert "persistent recall marker" in second[1]["result"]["context"]


def test_sidecar_isolates_operation_errors(tmp_path: Path) -> None:
    db_path = str(tmp_path / "errors.db")
    responses = _run_session(
        [
            serialize_sidecar_request_line(
                _request(
                    SidecarOperation.INITIALIZE,
                    InitializeParams(db_path=db_path),
                    correlation_id="init",
                )
            ),
            '{"protocol_version":"1.0","correlation_id":"bad","operation":"search","params":{"query":""}}',
            serialize_sidecar_request_line(
                _request(
                    SidecarOperation.SEARCH,
                    SearchParams(query="still works"),
                    correlation_id="good-search",
                )
            ),
            serialize_sidecar_request_line(
                _request(SidecarOperation.SHUTDOWN, {}, correlation_id="shutdown")
            ),
        ]
    )
    assert responses[1]["ok"] is False
    assert responses[1]["error"]["code"] == "VALIDATION_ERROR"
    assert responses[2]["ok"] is True
    assert responses[3]["ok"] is True


def test_sidecar_subprocess_cli_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "cli.db"
    payload = {
        "protocol_version": CURRENT_PROTOCOL_VERSION,
        "correlation_id": "cli-init",
        "operation": "initialize",
        "params": {"db_path": str(db_path)},
    }
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from hm_arch.integrations.openclaw.cli import run_openclaw_sidecar; "
            "raise SystemExit(run_openclaw_sidecar())",
        ],
        input=json.dumps(payload) + "\n",
        text=True,
        capture_output=True,
        check=False,
        cwd=_REPO_ROOT,
        timeout=30,
    )
    assert proc.returncode == 0
    line = proc.stdout.strip().splitlines()[0]
    response = json.loads(line)
    assert response["ok"] is True
    assert response["result"]["ready"] is True


@pytest.mark.benchmark
def test_sidecar_idle_and_query_overhead(tmp_path: Path) -> None:
    db_path = str(tmp_path / "bench.db")
    handlers = SidecarHandlers()
    server = SidecarServer(handlers=handlers)

    idle_started = time.perf_counter()
    health = handlers.dispatch(
        _request(
            SidecarOperation.INITIALIZE,
            InitializeParams(db_path=db_path),
            correlation_id="bench-init",
        )
    )
    idle_ms = (time.perf_counter() - idle_started) * 1000.0
    assert health.ok is True

    handlers.dispatch(
        _request(
            SidecarOperation.REMEMBER,
            RememberParams(content="benchmark memory"),
            correlation_id="bench-remember",
        )
    )

    query_started = time.perf_counter()
    search = handlers.dispatch(
        _request(
            SidecarOperation.SEARCH,
            SearchParams(query="benchmark"),
            correlation_id="bench-search",
        )
    )
    query_overhead_ms = (time.perf_counter() - query_started) * 1000.0
    assert search.ok is True
    assert search.telemetry is not None
    assert search.telemetry.query_latency_ms is not None

    # Structured measurements for benchmark collection.
    measurements = {
        "idle_initialize_ms": idle_ms,
        "per_query_overhead_ms": query_overhead_ms,
        "reported_query_latency_ms": search.telemetry.query_latency_ms,
    }
    assert measurements["idle_initialize_ms"] < 5_000
    assert measurements["per_query_overhead_ms"] < 5_000
    server.handlers.close()


def test_sidecar_validation_error_response_shape() -> None:
    responses = _run_session(['{"protocol_version":"1.0","operation":"search","params":{}}'])
    assert len(responses) == 1
    assert responses[0]["ok"] is False
    assert responses[0]["error"]["code"] == "VALIDATION_ERROR"


def test_sidecar_server_processes_multiple_writes_in_order(tmp_path: Path) -> None:
    db_path = str(tmp_path / "ordered.db")
    responses = _run_session(
        [
            serialize_sidecar_request_line(
                _request(
                    SidecarOperation.INITIALIZE,
                    InitializeParams(db_path=db_path),
                    correlation_id="init",
                )
            ),
            serialize_sidecar_request_line(
                _request(
                    SidecarOperation.REMEMBER,
                    RememberParams(content="first memory"),
                    correlation_id="remember-1",
                )
            ),
            serialize_sidecar_request_line(
                _request(
                    SidecarOperation.REMEMBER,
                    RememberParams(content="second memory"),
                    correlation_id="remember-2",
                )
            ),
            serialize_sidecar_request_line(
                _request(
                    SidecarOperation.SEARCH,
                    SearchParams(query="first second"),
                    correlation_id="search",
                )
            ),
            serialize_sidecar_request_line(
                _request(SidecarOperation.SHUTDOWN, {}, correlation_id="shutdown")
            ),
        ]
    )
    assert all(response["ok"] for response in responses[:4])
    assert responses[3]["result"]["result_count"] >= 2
