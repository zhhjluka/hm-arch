"""Tests for HM-Arch adapter runtime CLI (MEM-43).

All tests run offline without external LLM/API keys.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from hm_arch import EventType, HMArch, MemoryConfig
from hm_arch.integrations.cli.io import emit_adapter_response
from hm_arch.integrations.cli.main import main
from hm_arch.integrations.cli.runtime import (
    dispatch_adapter_request,
    execute_consolidate,
    execute_recall,
    execute_record,
)
from hm_arch.integrations.protocol import (
    ConsolidateRequest,
    RecallRequest,
    RecordRequest,
    fail_open_recall,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def cli_db_path() -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield str(Path(tmpdir) / "cli_runtime.db")


@pytest.fixture()
def cli_env(cli_db_path: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setenv("HM_ARCH_DB_PATH", cli_db_path)
    return {"HM_ARCH_DB_PATH": cli_db_path}


def _seed_memory(db_path: str) -> None:
    config = MemoryConfig(db_path=db_path, replay_sample_ratio=1.0)
    with HMArch(config=config) as memory:
        memory.add(
            "Repository uses uv and pytest for offline verification",
            event_type=EventType.OBSERVATION,
            importance=0.85,
        )


def test_execute_recall_returns_context(cli_db_path: str, cli_env: dict[str, str]) -> None:
    _seed_memory(cli_db_path)
    response = execute_recall(RecallRequest(task="offline pytest"))
    assert response.ok is True
    assert response.result_count >= 1
    assert "pytest" in response.context.lower() or "offline" in response.context.lower()
    assert response.error is None


def test_execute_record_persists_messages(cli_db_path: str, cli_env: dict[str, str]) -> None:
    response = execute_record(
        RecordRequest(
            user_message="What stack do we use?",
            agent_message="uv run pytest.",
        )
    )
    assert response.ok is True
    assert response.recorded_count == 2
    assert len(response.memory_ids) == 2

    config = MemoryConfig(db_path=cli_db_path, replay_sample_ratio=1.0)
    with HMArch(config=config) as memory:
        hits = memory.search("pytest", top_k=3)
        assert hits.results


def test_execute_consolidate_offline(cli_db_path: str, cli_env: dict[str, str]) -> None:
    config = MemoryConfig(db_path=cli_db_path, replay_sample_ratio=1.0)
    with HMArch(config=config) as memory:
        memory.add("Seed for consolidation", event_type=EventType.OBSERVATION)

    response = execute_consolidate(ConsolidateRequest())
    assert response.ok is True
    assert response.extracted_semantics >= 0


def test_dispatch_rejects_operation_mismatch(cli_env: dict[str, str]) -> None:
    response = dispatch_adapter_request(
        "recall",
        {"operation": "record", "user_message": "x"},
    )
    assert response.ok is False
    assert "does not match command" in (response.error or "")


def test_dispatch_fail_open_on_invalid_recall(cli_env: dict[str, str]) -> None:
    response = dispatch_adapter_request("recall", {})
    assert response.ok is False
    assert response.context == ""
    assert response.error


_CLI_MODULE = ["-m", "hm_arch.integrations.cli"]


def test_invalid_json_on_stdin_emits_fail_open(cli_env: dict[str, str]) -> None:
    proc = subprocess.run(
        [sys.executable, *_CLI_MODULE, "recall"],
        input="{not-json",
        text=True,
        capture_output=True,
        check=True,
        cwd=_REPO_ROOT,
        env={**cli_env, "PATH": os.environ.get("PATH", "")},
    )
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert "invalid JSON" in payload["error"]


def test_non_object_json_on_stdin_emits_fail_open(cli_env: dict[str, str]) -> None:
    proc = subprocess.run(
        [sys.executable, *_CLI_MODULE, "recall"],
        input="[]",
        text=True,
        capture_output=True,
        cwd=_REPO_ROOT,
        env={**cli_env, "PATH": os.environ.get("PATH", "")},
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert payload["context"] == ""
    assert "JSON object" in payload["error"]


def test_main_recall_subprocess(cli_db_path: str, cli_env: dict[str, str]) -> None:
    _seed_memory(cli_db_path)
    payload = json.dumps({"task": "offline pytest"})
    proc = subprocess.run(
        [sys.executable, *_CLI_MODULE, "recall"],
        input=payload,
        text=True,
        capture_output=True,
        check=True,
        cwd=_REPO_ROOT,
        env={**cli_env, "PATH": os.environ.get("PATH", "")},
    )
    out = json.loads(proc.stdout)
    assert out["ok"] is True
    assert out["result_count"] >= 1


@pytest.mark.parametrize("command", ["recall", "record", "consolidate"])
def test_main_help_lists_commands(command: str) -> None:
    with pytest.raises(SystemExit) as exc:
        main([command, "--help"])
    assert exc.value.code == 0


def _resolve_hm_arch_console_script() -> str | None:
    on_path = shutil.which("hm-arch")
    if on_path:
        return on_path
    venv_script = _REPO_ROOT / ".venv" / "bin" / "hm-arch"
    if venv_script.is_file():
        return str(venv_script)
    return None


def test_installed_entry_point_smoke(cli_db_path: str, cli_env: dict[str, str]) -> None:
    """Verify the packaged ``hm-arch`` console script from the project venv."""
    hm_arch_bin = _resolve_hm_arch_console_script()
    if hm_arch_bin is None:
        pytest.skip("hm-arch console script not installed in active environment")

    _seed_memory(cli_db_path)
    for command, payload_obj in (
        ("recall", {"task": "offline pytest"}),
        ("record", {"user_message": "hello", "agent_message": "world"}),
        ("consolidate", {}),
    ):
        proc = subprocess.run(
            [str(hm_arch_bin), command],
            input=json.dumps(payload_obj),
            text=True,
            capture_output=True,
            check=True,
            env={**cli_env, "PATH": os.environ.get("PATH", "")},
        )
        out = json.loads(proc.stdout)
        assert out["ok"] is True, proc.stderr


def test_fail_open_recall_emitted_as_json(capsys: pytest.CaptureFixture[str]) -> None:
    emit_adapter_response(fail_open_recall("database locked"))
    out = json.loads(capsys.readouterr().out.strip())
    assert out["ok"] is False
    assert out["error"] == "database locked"
