"""Tests for the stable agent adapter protocol (MEM-39).

All tests run offline without external LLM/API keys.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from hm_arch.integrations.protocol import (
    AdapterOperation,
    ConsolidateRequest,
    ConsolidateResponse,
    ProtocolValidationError,
    RecallRequest,
    RecallResponse,
    RecordRequest,
    RecordResponse,
    fail_open_consolidate,
    fail_open_recall,
    fail_open_record,
    parse_adapter_request,
    validate_operation,
)


def _field_names(cls: type) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


class TestAdapterOperation:
    def test_supported_operations(self) -> None:
        assert {op.value for op in AdapterOperation} == {
            "recall",
            "record",
            "consolidate",
        }

    @pytest.mark.parametrize("value", ["recall", "record", "consolidate", "RECALL"])
    def test_validate_operation_accepts_supported_values(self, value: str) -> None:
        assert validate_operation(value) is AdapterOperation(value.lower())

    @pytest.mark.parametrize("value", ["search", "delete", ""])
    def test_validate_operation_rejects_unknown_values(self, value: str) -> None:
        with pytest.raises(ProtocolValidationError, match="Unsupported operation"):
            validate_operation(value)


class TestRecallRequest:
    def test_parse_valid_payload(self) -> None:
        request = parse_adapter_request(
            {
                "operation": "recall",
                "task": "How do we run offline tests?",
                "top_k": 3,
            }
        )
        assert isinstance(request, RecallRequest)
        assert request.task == "How do we run offline tests?"
        assert request.top_k == 3

    def test_parse_accepts_hook_style_prompt_field(self) -> None:
        request = parse_adapter_request(
            {"operation": "recall", "prompt": "offline agent hooks"}
        )
        assert isinstance(request, RecallRequest)
        assert request.task == "offline agent hooks"

    @pytest.mark.parametrize(
        "payload",
        [
            {"operation": "recall"},
            {"operation": "recall", "task": ""},
            {"operation": "recall", "task": "   "},
            {"operation": "recall", "top_k": 0},
            {"operation": "recall", "task": "ok", "top_k": -1},
        ],
    )
    def test_rejects_malformed_recall_payload(self, payload: dict) -> None:
        with pytest.raises(ProtocolValidationError):
            parse_adapter_request(payload)

    def test_response_fields(self) -> None:
        assert {"ok", "context", "result_count", "truncated", "error"} <= _field_names(
            RecallResponse
        )


class TestRecordRequest:
    def test_parse_valid_payload(self) -> None:
        request = parse_adapter_request(
            {
                "operation": "record",
                "user_message": "What stack do we use?",
                "agent_message": "uv run pytest.",
            }
        )
        assert isinstance(request, RecordRequest)
        assert request.user_message == "What stack do we use?"
        assert request.agent_message == "uv run pytest."

    def test_parse_accepts_hook_style_fields(self) -> None:
        request = parse_adapter_request(
            {
                "operation": "record",
                "prompt": "Record this turn",
                "last_assistant_message": "Turn stored.",
            }
        )
        assert isinstance(request, RecordRequest)
        assert request.user_message == "Record this turn"
        assert request.agent_message == "Turn stored."

    @pytest.mark.parametrize(
        "payload",
        [
            {"operation": "record"},
            {"operation": "record", "user_message": "", "agent_message": ""},
            {"operation": "record", "user_message": "   ", "agent_message": "   "},
        ],
    )
    def test_rejects_empty_record_payload(self, payload: dict) -> None:
        with pytest.raises(ProtocolValidationError):
            parse_adapter_request(payload)

    def test_response_fields(self) -> None:
        assert {"ok", "memory_ids", "recorded_count", "error"} <= _field_names(
            RecordResponse
        )


class TestConsolidateRequest:
    def test_parse_valid_payload(self) -> None:
        request = parse_adapter_request({"operation": "consolidate"})
        assert isinstance(request, ConsolidateRequest)

    def test_parse_accepts_empty_hook_payload(self) -> None:
        request = parse_adapter_request({"operation": "consolidate", "session_id": "s-1"})
        assert isinstance(request, ConsolidateRequest)
        assert request.session_id == "s-1"

    def test_response_fields(self) -> None:
        assert {
            "ok",
            "extracted_semantics",
            "merged_duplicates",
            "scheduled_reviews",
            "archived_to_l4",
            "error",
        } <= _field_names(ConsolidateResponse)


class TestMalformedEnvelope:
    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"operation": 123},
            {"operation": "recall", "task": ["not", "a", "string"]},
            {"operation": "record", "user_message": 42},
            {"operation": "consolidate", "force": "yes"},
        ],
    )
    def test_rejects_malformed_payloads(self, payload: dict) -> None:
        with pytest.raises(ProtocolValidationError):
            parse_adapter_request(payload)

    def test_rejects_non_object_json(self) -> None:
        with pytest.raises(ProtocolValidationError):
            parse_adapter_request(json.loads('["recall"]'))


class TestFailOpenResponses:
    """Fail-open responses must never block host agents."""

    def test_fail_open_recall_shape(self) -> None:
        response = fail_open_recall("database locked")
        assert response.ok is False
        assert response.context == ""
        assert response.result_count == 0
        assert response.truncated is False
        assert response.error == "database locked"

    def test_fail_open_record_shape(self) -> None:
        response = fail_open_record("write failed")
        assert response.ok is False
        assert response.memory_ids == []
        assert response.recorded_count == 0
        assert response.error == "write failed"

    def test_fail_open_consolidate_shape(self) -> None:
        response = fail_open_consolidate("consolidation skipped")
        assert response.ok is False
        assert response.extracted_semantics == 0
        assert response.merged_duplicates == 0
        assert response.scheduled_reviews == 0
        assert response.archived_to_l4 == 0
        assert response.error == "consolidation skipped"

    def test_fail_open_responses_are_json_serializable(self) -> None:
        payloads = [
            dataclasses.asdict(fail_open_recall("x")),
            dataclasses.asdict(fail_open_record("x")),
            dataclasses.asdict(fail_open_consolidate("x")),
        ]
        for payload in payloads:
            assert json.loads(json.dumps(payload)) == payload
