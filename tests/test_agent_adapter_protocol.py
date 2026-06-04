"""Tests for agent adapter protocol, configuration, and fail-open behavior (HM-39)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from hm_arch import EventType, HMArch, MemoryConfig
from hm_arch.integrations import (
    FAIL_OPEN_ERROR_CODES,
    IntegrationConfig,
    IntegrationScope,
    ProtocolValidationError,
    execute_adapter_request,
    fail_open_response,
    parse_adapter_request,
)
from hm_arch.integrations.protocol import (
    AgentOperation,
    ConsolidateRequest,
    RecallRequest,
    RecordRequest,
)


@pytest.fixture()
def adapter_db_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield str(Path(tmpdir) / "adapter_protocol.db")


def test_integration_config_offline_first_defaults() -> None:
    cfg = IntegrationConfig()
    assert cfg.enable_llm_providers is False
    assert cfg.provider_fallback_to_local is True
    assert cfg.scope == IntegrationScope.PROJECT
    assert cfg.db_path == "./.hm_arch_agent_memory.db"
    assert cfg.recall_top_k == 5
    assert cfg.max_context_chars == 8192
    assert cfg.consolidation_enabled is True

    memory_cfg = cfg.to_memory_config()
    assert memory_cfg.enable_llm_providers is False
    assert memory_cfg.auto_consolidate is False


def test_integration_config_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="recall_top_k"):
        IntegrationConfig(recall_top_k=0)
    with pytest.raises(ValueError, match="memory_preset"):
        IntegrationConfig(memory_preset="unknown_preset")


def test_integration_config_from_dict_round_trip() -> None:
    cfg = IntegrationConfig(
        db_path="./custom.db",
        recall_top_k=3,
        memory_preset="code_agent",
    )
    restored = IntegrationConfig.from_dict({**cfg.to_dict(), "extra_ignored": True})
    assert restored.db_path == "./custom.db"
    assert restored.recall_top_k == 3
    assert restored.memory_preset == "code_agent"


def test_integration_config_env_db_path_override(
    adapter_db_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HM_ARCH_DB_PATH", adapter_db_path)
    cfg = IntegrationConfig(db_path="./ignored.db")
    assert cfg.resolve_db_path() == adapter_db_path
    assert cfg.to_memory_config().db_path == adapter_db_path


def test_parse_adapter_request_recall_record_consolidate() -> None:
    recall = parse_adapter_request({"operation": "recall", "task": "pytest setup"})
    assert isinstance(recall, RecallRequest)
    assert recall.task == "pytest setup"

    record = parse_adapter_request(
        {
            "operation": "record",
            "user_message": "hello",
            "agent_message": "world",
        }
    )
    assert isinstance(record, RecordRequest)
    assert record.user_message == "hello"

    consolidate = parse_adapter_request({"operation": "consolidate"})
    assert isinstance(consolidate, ConsolidateRequest)


@pytest.mark.parametrize(
    "payload,match",
    [
        ("not-a-dict", "JSON object"),
        ({}, "operation"),
        ({"operation": 42}, "operation"),
        ({"operation": "delete"}, "Unsupported operation"),
        ({"operation": "recall", "task": 1}, "task"),
        ({"operation": "recall", "top_k": "five"}, "top_k"),
        ({"operation": "record", "user_message": []}, "user_message"),
    ],
)
def test_parse_adapter_request_rejects_malformed(payload, match: str) -> None:
    with pytest.raises(ProtocolValidationError, match=match):
        parse_adapter_request(payload)


def test_fail_open_response_shape() -> None:
    response = fail_open_response(
        "recall",
        error_code="INVALID_PAYLOAD",
        message="bad payload",
        detail={"field": "task"},
    )
    assert response["ok"] is False
    assert response["operation"] == "recall"
    assert response["error_code"] in FAIL_OPEN_ERROR_CODES
    assert response["detail"] == {"field": "task"}
    json.dumps(response)


def test_execute_adapter_request_fail_open_on_malformed_payload() -> None:
    response = execute_adapter_request({"operation": "recall", "task": 123})
    assert response["ok"] is False
    assert response["error_code"] == "INVALID_PAYLOAD"


def test_execute_adapter_request_recall_record_consolidate(
    adapter_db_path: str,
) -> None:
    cfg = IntegrationConfig(db_path=adapter_db_path, recall_top_k=3)

    seed_cfg = MemoryConfig(db_path=adapter_db_path, replay_sample_ratio=1.0)
    with HMArch(config=seed_cfg) as memory:
        memory.add(
            "Repository uses uv and pytest",
            event_type=EventType.OBSERVATION,
            importance=0.9,
        )

    recall = execute_adapter_request(
        {"operation": "recall", "task": "offline pytest"},
        config=cfg,
    )
    assert recall["ok"] is True
    assert recall["operation"] == "recall"
    assert recall["hit_count"] >= 1
    assert "pytest" in recall["context"].lower()

    record = execute_adapter_request(
        {
            "operation": "record",
            "user_message": "Run tests with uv",
            "agent_message": "Use uv run pytest.",
        },
        config=cfg,
    )
    assert record["ok"] is True
    assert len(record["memory_ids"]) == 2

    consolidate = execute_adapter_request({"operation": "consolidate"}, config=cfg)
    assert consolidate["ok"] is True
    assert consolidate["skipped"] is False
    assert consolidate["duration_seconds"] >= 0.0


def test_execute_adapter_request_empty_recall_task_succeeds(
    adapter_db_path: str,
) -> None:
    cfg = IntegrationConfig(db_path=adapter_db_path)
    response = execute_adapter_request({"operation": "recall", "task": "  "}, config=cfg)
    assert response["ok"] is True
    assert response["context"] == ""
    assert response["hit_count"] == 0


def test_execute_adapter_request_consolidation_disabled(
    adapter_db_path: str,
) -> None:
    cfg = IntegrationConfig(db_path=adapter_db_path, consolidation_enabled=False)
    response = execute_adapter_request({"operation": "consolidate"}, config=cfg)
    assert response["ok"] is True
    assert response["skipped"] is True


def test_recall_context_truncation(adapter_db_path: str) -> None:
    cfg = IntegrationConfig(
        db_path=adapter_db_path,
        max_context_chars=40,
        recall_top_k=5,
    )
    seed_cfg = MemoryConfig(db_path=adapter_db_path, replay_sample_ratio=1.0)
    with HMArch(config=seed_cfg) as memory:
        for index in range(5):
            memory.add(
                f"Long memory entry number {index} with extra searchable tokens",
                event_type=EventType.OBSERVATION,
                importance=0.8,
            )

    response = execute_adapter_request(
        {"operation": "recall", "task": "searchable tokens"},
        config=cfg,
    )
    assert response["ok"] is True
    assert response["truncated"] is True
    assert len(response["context"]) <= 40


def test_agent_operation_values_match_protocol() -> None:
    assert AgentOperation.RECALL.value == "recall"
    assert AgentOperation.RECORD.value == "record"
    assert AgentOperation.CONSOLIDATE.value == "consolidate"


def test_integration_config_preset_applies(adapter_db_path: str) -> None:
    cfg = IntegrationConfig(
        db_path=adapter_db_path,
        memory_preset="code_agent",
    )
    memory_cfg = cfg.to_memory_config()
    preset = MemoryConfig.preset("code_agent")
    assert memory_cfg.consolidate_interval_hours == preset.consolidate_interval_hours
    assert memory_cfg.l2_fast_tau == preset.l2_fast_tau


def test_fail_open_invalid_config(adapter_db_path: str) -> None:
    cfg = IntegrationConfig(db_path=adapter_db_path)
    cfg.recall_top_k = 0
    response = execute_adapter_request({"operation": "recall", "task": "x"}, config=cfg)
    assert response["ok"] is False
    assert response["error_code"] == "INVALID_CONFIG"
