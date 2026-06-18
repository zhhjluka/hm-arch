"""Offline integration tests for the HM-Arch OpenClaw sidecar server (MEM-69)."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from hm_arch.integrations.openclaw.sidecar import SidecarServer, run_stdio_server
from hm_arch.integrations.sidecar.protocol import (
    CURRENT_PROTOCOL_VERSION,
    serialize_sidecar_request_line,
)


def _request(
    operation: str,
    params: dict[str, Any],
    *,
    correlation_id: str,
    timeout_ms: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "protocol_version": CURRENT_PROTOCOL_VERSION,
        "correlation_id": correlation_id,
        "operation": operation,
        "params": params,
    }
    if timeout_ms is not None:
        payload["timeout_ms"] = timeout_ms
    return payload


def _initialize(db_path: str, *, correlation_id: str = "init-1") -> dict[str, Any]:
    return _request(
        "initialize",
        {
            "db_path": db_path,
            "client_capabilities": ["telemetry.v1", "forget.by_query.v1"],
            "config": {"preset": "code_agent"},
        },
        correlation_id=correlation_id,
    )


class SidecarProcess:
    """Subprocess wrapper for ``hm-arch openclaw sidecar``."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "hm_arch.integrations.cli.main", "openclaw", "sidecar"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert self.proc.stdin is not None
        assert self.proc.stdout is not None
        init = self.exchange(_initialize(db_path))
        assert init["ok"] is True

    def exchange(self, payload: dict[str, Any]) -> dict[str, Any]:
        assert self.proc.stdin is not None
        assert self.proc.stdout is not None
        self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        assert line.strip(), "sidecar closed stdout unexpectedly"
        return json.loads(line)

    def shutdown(self) -> None:
        self.exchange(_request("shutdown", {}, correlation_id="shutdown-1"))

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                self.shutdown()
            except AssertionError:
                self.proc.kill()
        if self.proc.stdin:
            self.proc.stdin.close()
        self.proc.wait(timeout=5)


@pytest.fixture
def sidecar_db(tmp_path: Path) -> str:
    return str(tmp_path / "sidecar-memory.db")


class TestSidecarServerInProcess:
    def test_initialize_health_shutdown(self, sidecar_db: str) -> None:
        server = SidecarServer()
        init = server.handle_line(
            json.dumps(_initialize(sidecar_db), ensure_ascii=False)
        )
        init_payload = json.loads(init)
        assert init_payload["ok"] is True
        assert init_payload["result"]["ready"] is True

        health = json.loads(
            server.handle_line(
                json.dumps(
                    _request("health", {"deep": True}, correlation_id="health-1"),
                    ensure_ascii=False,
                )
            )
        )
        assert health["ok"] is True
        assert health["result"]["db_reachable"] is True
        assert "total_memories" in health["result"]["stats"]

        shutdown = json.loads(
            server.handle_line(
                json.dumps(
                    _request("shutdown", {}, correlation_id="shutdown-1"),
                    ensure_ascii=False,
                )
            )
        )
        assert shutdown["ok"] is True
        assert shutdown["result"]["shutdown_ack"] is True

    def test_remember_search_and_telemetry(self, sidecar_db: str) -> None:
        server = SidecarServer()
        server.handle_line(json.dumps(_initialize(sidecar_db), ensure_ascii=False))

        remember = json.loads(
            server.handle_line(
                json.dumps(
                    _request(
                        "remember",
                        {
                            "content": "user likes Python for offline tooling",
                            "importance": 0.8,
                        },
                        correlation_id="remember-1",
                    ),
                    ensure_ascii=False,
                )
            )
        )
        assert remember["ok"] is True
        assert remember["result"]["recorded"] is True
        assert remember["telemetry"]["storage_latency_ms"] >= 0

        search = json.loads(
            server.handle_line(
                json.dumps(
                    _request(
                        "search",
                        {"query": "Python tooling", "top_k": 3},
                        correlation_id="search-1",
                    ),
                    ensure_ascii=False,
                )
            )
        )
        assert search["ok"] is True
        assert search["result"]["result_count"] >= 1
        telemetry = search["telemetry"]
        assert telemetry["query_latency_ms"] >= 0
        assert telemetry["hit_count"] >= 1
        assert telemetry["returned_characters"] >= 0
        assert telemetry["returned_tokens"] >= 0

    def test_store_restart_recall(self, sidecar_db: str) -> None:
        content = "persistent recall marker for sidecar restart"
        first = SidecarProcess(sidecar_db)
        remember = first.exchange(
            _request(
                "remember",
                {"content": content, "importance": 0.9},
                correlation_id="remember-restart",
            )
        )
        assert remember["ok"] is True
        first.close()

        second = SidecarProcess(sidecar_db)
        search = second.exchange(
            _request(
                "search",
                {"query": "persistent recall marker", "top_k": 5},
                correlation_id="search-restart",
            )
        )
        second.close()
        assert search["ok"] is True
        assert search["result"]["result_count"] >= 1
        assert any(content in hit["content"] for hit in search["result"]["hits"])

    def test_fail_open_search_error_isolated(self, sidecar_db: str) -> None:
        server = SidecarServer()
        server.handle_line(json.dumps(_initialize(sidecar_db), ensure_ascii=False))

        with patch.object(
            type(server.memory),
            "search",
            side_effect=RuntimeError("database is locked"),
        ):
            failed = json.loads(
                server.handle_line(
                    json.dumps(
                        _request(
                            "search",
                            {"query": "anything"},
                            correlation_id="search-fail",
                        ),
                        ensure_ascii=False,
                    )
                )
            )
        assert failed["ok"] is False
        assert failed["result"]["result_count"] == 0
        assert failed["error"]["code"] == "STORAGE_ERROR"

        ok = json.loads(
            server.handle_line(
                json.dumps(
                    _request(
                        "remember",
                        {"content": "still writable after search failure"},
                        correlation_id="remember-after-fail",
                    ),
                    ensure_ascii=False,
                )
            )
        )
        assert ok["ok"] is True

    def test_consolidate_error_does_not_break_health(self, sidecar_db: str) -> None:
        server = SidecarServer()
        server.handle_line(json.dumps(_initialize(sidecar_db), ensure_ascii=False))

        with patch(
            "hm_arch.integrations.openclaw.sidecar.run_idle_consolidation",
            side_effect=RuntimeError("consolidation failed"),
        ):
            failed = json.loads(
                server.handle_line(
                    json.dumps(
                        _request("consolidate", {}, correlation_id="consolidate-fail"),
                        ensure_ascii=False,
                    )
                )
            )
        assert failed["ok"] is False
        assert failed["error"]["code"] == "STORAGE_ERROR"

        health = json.loads(
            server.handle_line(
                json.dumps(
                    _request("health", {}, correlation_id="health-after-fail"),
                    ensure_ascii=False,
                )
            )
        )
        assert health["ok"] is True

    def test_validation_error_fail_open_shape(self, sidecar_db: str) -> None:
        server = SidecarServer()
        server.handle_line(json.dumps(_initialize(sidecar_db), ensure_ascii=False))
        response = json.loads(
            server.handle_line(
                json.dumps(
                    _request("search", {"query": ""}, correlation_id="bad-search"),
                    ensure_ascii=False,
                )
            )
        )
        assert response["ok"] is False
        assert response["error"]["code"] == "VALIDATION_ERROR"
        assert response["result"]["result_count"] == 0

    def test_not_initialized_fail_open_search(self) -> None:
        server = SidecarServer()
        response = json.loads(
            server.handle_line(
                json.dumps(
                    _request("search", {"query": "hello"}, correlation_id="no-init"),
                    ensure_ascii=False,
                )
            )
        )
        assert response["ok"] is False
        assert response["error"]["code"] == "NOT_INITIALIZED"

    def test_forget_by_query_requires_capability(self, sidecar_db: str) -> None:
        server = SidecarServer()
        server.handle_line(
            json.dumps(
                _request(
                    "initialize",
                    {
                        "db_path": sidecar_db,
                        "client_capabilities": ["telemetry.v1"],
                    },
                    correlation_id="init-no-forget-query",
                ),
                ensure_ascii=False,
            )
        )
        response = json.loads(
            server.handle_line(
                json.dumps(
                    _request(
                        "forget",
                        {"query": "Python"},
                        correlation_id="forget-query",
                    ),
                    ensure_ascii=False,
                )
            )
        )
        assert response["ok"] is False
        assert response["error"]["code"] == "VALIDATION_ERROR"


class TestSidecarStdioLoop:
    def test_run_stdio_server_processes_lines(self, sidecar_db: str) -> None:
        stdin = io.StringIO(
            "\n".join(
                [
                    json.dumps(_initialize(sidecar_db)),
                    json.dumps(
                        _request("health", {}, correlation_id="health-stdio")
                    ),
                    json.dumps(
                        _request("shutdown", {}, correlation_id="shutdown-stdio")
                    ),
                ]
            )
            + "\n"
        )
        stdout = io.StringIO()
        exit_code = run_stdio_server(stdin=stdin, stdout=stdout)
        assert exit_code == 0
        lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
        assert len(lines) == 3
        payloads = [json.loads(line) for line in lines]
        assert payloads[0]["operation"] == "initialize"
        assert payloads[1]["operation"] == "health"
        assert payloads[2]["operation"] == "shutdown"


class TestSidecarTelemetryBenchmarks:
    def test_idle_health_and_query_overhead(self, sidecar_db: str) -> None:
        server = SidecarServer()
        server.handle_line(json.dumps(_initialize(sidecar_db), ensure_ascii=False))

        idle_started = time.perf_counter()
        idle_health = json.loads(
            server.handle_line(
                json.dumps(
                    _request("health", {}, correlation_id="idle-health"),
                    ensure_ascii=False,
                )
            )
        )
        idle_ms = (time.perf_counter() - idle_started) * 1000.0
        assert idle_health["ok"] is True
        assert idle_ms < 500.0

        server.handle_line(
            json.dumps(
                _request(
                    "remember",
                    {"content": "benchmark query seed content"},
                    correlation_id="seed",
                ),
                ensure_ascii=False,
            )
        )

        query_started = time.perf_counter()
        search = json.loads(
            server.handle_line(
                json.dumps(
                    _request(
                        "search",
                        {"query": "benchmark query seed"},
                        correlation_id="bench-search",
                    ),
                    ensure_ascii=False,
                )
            )
        )
        wall_ms = (time.perf_counter() - query_started) * 1000.0
        assert search["ok"] is True
        assert search["telemetry"]["query_latency_ms"] >= 0
        assert wall_ms < 2000.0

    def test_sequential_reads_after_write(self, sidecar_db: str) -> None:
        server = SidecarServer()
        server.handle_line(json.dumps(_initialize(sidecar_db), ensure_ascii=False))
        server.handle_line(
            json.dumps(
                _request(
                    "remember",
                    {"content": "sequential read probe"},
                    correlation_id="seed-sequential",
                ),
                ensure_ascii=False,
            )
        )

        results: list[dict[str, Any]] = []
        for index in range(4):
            line = server.handle_line(
                json.dumps(
                    _request(
                        "search",
                        {"query": "sequential read probe"},
                        correlation_id=f"read-{index}",
                    ),
                    ensure_ascii=False,
                )
            )
            results.append(json.loads(line))

        assert len(results) == 4
        assert all(item["ok"] is True for item in results)
