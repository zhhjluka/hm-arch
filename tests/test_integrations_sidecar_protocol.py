"""Tests for the HM-Arch JSONL sidecar protocol (MEM-66).

All tests run offline against shared golden fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hm_arch.integrations.sidecar.protocol import (
    CURRENT_PROTOCOL_VERSION,
    FAIL_OPEN_OPERATIONS,
    SUPPORTED_OPERATIONS,
    ProtocolValidationError,
    SidecarOperation,
    fail_open_record_turn,
    fail_open_remember,
    fail_open_search,
    negotiate_capabilities,
    negotiate_protocol_version,
    parse_sidecar_request,
    parse_sidecar_request_line,
    parse_sidecar_response,
    parse_sidecar_response_line,
    serialize_sidecar_request,
    serialize_sidecar_response,
    validate_operation,
    validate_protocol_version,
)

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "sidecar-protocol"
MANIFEST_PATH = FIXTURES_ROOT / "manifest.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture_pairs() -> list[tuple[str, Path, Path, bool]]:
    manifest = _load_json(MANIFEST_PATH)
    pairs: list[tuple[str, Path, Path, bool]] = []
    for entry in manifest["fixtures"]:
        pairs.append(
            (
                entry["id"],
                FIXTURES_ROOT / entry["request"],
                FIXTURES_ROOT / entry["response"],
                bool(entry.get("invalid_request", False)),
            )
        )
    return pairs


class TestSupportedOperations:
    def test_all_required_operations_are_supported(self) -> None:
        assert SUPPORTED_OPERATIONS == {
            "initialize",
            "health",
            "search",
            "remember",
            "forget",
            "record_turn",
            "consolidate",
            "shutdown",
        }

    def test_fail_open_operations(self) -> None:
        assert FAIL_OPEN_OPERATIONS == {"search", "remember", "record_turn"}


class TestProtocolVersioning:
    def test_negotiate_same_version(self) -> None:
        assert negotiate_protocol_version("1.0") == "1.0"

    def test_negotiate_lower_client_minor(self) -> None:
        assert negotiate_protocol_version("1.0", server_version="1.2") == "1.0"

    def test_negotiate_lower_server_minor(self) -> None:
        assert negotiate_protocol_version("1.2", server_version="1.0") == "1.0"

    def test_rejects_incompatible_major(self) -> None:
        with pytest.raises(ProtocolValidationError, match="Incompatible protocol major"):
            validate_protocol_version("2.0", server_version="1.0")


class TestCapabilityNegotiation:
    def test_intersection(self) -> None:
        server, negotiated = negotiate_capabilities(
            ["telemetry.v1", "unknown.v9"],
            server_capabilities=["telemetry.v1", "health.deep.v1"],
        )
        assert server == ("telemetry.v1", "health.deep.v1")
        assert negotiated == ("telemetry.v1",)


@pytest.mark.parametrize(
    "fixture_id,request_path,response_path,invalid_request",
    _fixture_pairs(),
)
def test_golden_fixture_round_trip(
    fixture_id: str,
    request_path: Path,
    response_path: Path,
    invalid_request: bool,
) -> None:
    request_data = _load_json(request_path)
    response_data = _load_json(response_path)

    if invalid_request:
        with pytest.raises(ProtocolValidationError):
            parse_sidecar_request(request_data)
    else:
        request = parse_sidecar_request(request_data)
        assert request.correlation_id == request_data["correlation_id"]
        assert request.operation.value == request_data["operation"]
        assert serialize_sidecar_request(request) == request_data

    response = parse_sidecar_response(response_data)
    assert response.correlation_id == response_data["correlation_id"]
    assert response.operation.value == response_data["operation"]
    if not invalid_request:
        request = parse_sidecar_request(request_data)
        assert response.correlation_id == request.correlation_id
        assert response.operation == request.operation

    assert serialize_sidecar_response(response) == response_data


def test_full_session_jsonl_transcript() -> None:
    manifest = _load_json(MANIFEST_PATH)
    transcript_path = FIXTURES_ROOT / manifest["transcript"]
    lines = [line for line in transcript_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) >= 2
    assert len(lines) % 2 == 0

    for index in range(0, len(lines), 2):
        request = parse_sidecar_request_line(lines[index])
        response = parse_sidecar_response_line(lines[index + 1])
        assert response.correlation_id == request.correlation_id
        assert response.operation == request.operation


class TestValidationErrors:
    @pytest.mark.parametrize(
      "payload",
      [
          {},
          {"protocol_version": "1.0"},
          {"protocol_version": "1.0", "correlation_id": "x", "operation": "noop", "params": {}},
          {"protocol_version": "2.0", "correlation_id": "x", "operation": "health", "params": {}},
          {
              "protocol_version": "1.0",
              "correlation_id": "x",
              "operation": "search",
              "params": {"query": ""},
          },
      ],
    )
    def test_rejects_invalid_requests(self, payload: dict) -> None:
        with pytest.raises(ProtocolValidationError):
            parse_sidecar_request(payload)


class TestFailOpenResponses:
    def test_fail_open_search_shape(self) -> None:
        response = fail_open_search("corr-1", "database locked")
        assert response.ok is False
        assert response.operation is SidecarOperation.SEARCH
        assert response.result.context == ""
        assert response.result.result_count == 0
        assert response.error is not None
        assert response.error.retryable is True

    def test_fail_open_remember_shape(self) -> None:
        response = fail_open_remember("corr-2", "write failed")
        assert response.ok is False
        assert response.result.memory_id is None
        assert response.result.recorded is False

    def test_fail_open_record_turn_shape(self) -> None:
        response = fail_open_record_turn("corr-3", "capture failed")
        assert response.ok is False
        assert response.result.memory_ids == ()
        assert response.result.recorded_count == 0

    def test_fail_open_responses_are_json_serializable(self) -> None:
        payloads = [
            serialize_sidecar_response(fail_open_search("a", "x")),
            serialize_sidecar_response(fail_open_remember("b", "x")),
            serialize_sidecar_response(fail_open_record_turn("c", "x")),
        ]
        for payload in payloads:
            assert json.loads(json.dumps(payload)) == payload


class TestOperationValidation:
    @pytest.mark.parametrize("value", ["search", "RECORD_TURN", "health"])
    def test_validate_operation_accepts_supported(self, value: str) -> None:
        assert validate_operation(value).value == value.lower()

    def test_current_protocol_version(self) -> None:
        assert CURRENT_PROTOCOL_VERSION == "1.0"


class TestAdversarialEnvelopeValidation:
    """Strict validation for malformed envelopes and typed fields."""

    def test_missing_operation_raises_protocol_validation_error(self) -> None:
        with pytest.raises(ProtocolValidationError, match="operation is required"):
            parse_sidecar_request(
                {
                    "protocol_version": "1.0",
                    "correlation_id": "x",
                    "params": {},
                }
            )

    def test_missing_operation_on_response_raises_protocol_validation_error(self) -> None:
        with pytest.raises(ProtocolValidationError, match="operation is required"):
            parse_sidecar_response(
                {
                    "protocol_version": "1.0",
                    "correlation_id": "x",
                    "ok": True,
                    "result": {},
                    "error": None,
                }
            )

    @pytest.mark.parametrize(
        "db_reachable",
        ["false", "true", 1, 0],
    )
    def test_rejects_non_boolean_db_reachable(self, db_reachable: object) -> None:
        with pytest.raises(ProtocolValidationError, match="db_reachable must be a boolean"):
            parse_sidecar_response(
                {
                    "protocol_version": "1.0",
                    "correlation_id": "x",
                    "operation": "health",
                    "ok": True,
                    "result": {"status": "healthy", "db_reachable": db_reachable},
                    "error": None,
                }
            )

    @pytest.mark.parametrize(
        "field,value",
        [
            ("result_count", "1"),
            ("result_count", 1.5),
            ("extracted_semantics", "0"),
        ],
    )
    def test_rejects_non_integer_result_fields(self, field: str, value: object) -> None:
        base_result = {
            "context": "",
            "hits": [],
            "result_count": 0,
            "truncated": False,
        }
        if field.startswith("extracted"):
            payload = {
                "protocol_version": "1.0",
                "correlation_id": "x",
                "operation": "consolidate",
                "ok": True,
                "result": {
                    "extracted_semantics": 0,
                    "merged_duplicates": 0,
                    "scheduled_reviews": 0,
                    "archived_to_l4": 0,
                    field: value,
                },
                "error": None,
            }
        else:
            base_result[field] = value
            payload = {
                "protocol_version": "1.0",
                "correlation_id": "x",
                "operation": "search",
                "ok": True,
                "result": base_result,
                "error": None,
            }
        with pytest.raises(ProtocolValidationError, match=f"{field} must be an integer"):
            parse_sidecar_response(payload)

    @pytest.mark.parametrize(
        "hit_patch,match",
        [
            ({"content": 42}, "content must be a string"),
            ({"layer": "3"}, "layer must be an integer"),
            ({"score": "0.8"}, "score must be a number"),
            ({"retention": False}, "retention must be a number"),
        ],
    )
    def test_rejects_malformed_search_hit_fields(
        self, hit_patch: dict, match: str
    ) -> None:
        hit = {
            "memory_id": "mem-1",
            "layer": 3,
            "content": "hello",
            "score": 0.8,
            "retention": 0.9,
        }
        hit.update(hit_patch)
        with pytest.raises(ProtocolValidationError, match=match):
            parse_sidecar_response(
                {
                    "protocol_version": "1.0",
                    "correlation_id": "x",
                    "operation": "search",
                    "ok": True,
                    "result": {
                        "context": "",
                        "hits": [hit],
                        "result_count": 1,
                        "truncated": False,
                    },
                    "error": None,
                }
            )

    def test_initialize_error_without_success_result_is_accepted(self) -> None:
        response = parse_sidecar_response(
            {
                "protocol_version": "1.0",
                "correlation_id": "x",
                "operation": "initialize",
                "ok": False,
                "result": {},
                "error": {
                    "code": "STORAGE_ERROR",
                    "message": "cannot open database",
                    "retryable": True,
                },
            }
        )
        assert response.ok is False
        assert response.result == {}
        assert response.error is not None
        assert response.error.code == "STORAGE_ERROR"

    def test_successful_response_must_not_include_error(self) -> None:
        with pytest.raises(
            ProtocolValidationError, match="successful responses must not include error"
        ):
            parse_sidecar_response(
                {
                    "protocol_version": "1.0",
                    "correlation_id": "x",
                    "operation": "health",
                    "ok": True,
                    "result": {"status": "healthy", "db_reachable": True},
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "should not be here",
                        "retryable": True,
                    },
                }
            )

    def test_failed_response_must_include_error(self) -> None:
        with pytest.raises(
            ProtocolValidationError, match="failed responses must include error"
        ):
            parse_sidecar_response(
                {
                    "protocol_version": "1.0",
                    "correlation_id": "x",
                    "operation": "search",
                    "ok": False,
                    "result": {
                        "context": "",
                        "hits": [],
                        "result_count": 0,
                        "truncated": False,
                    },
                    "error": None,
                }
            )

    def test_fail_open_error_responses_still_validate_result_shape(self) -> None:
        response = parse_sidecar_response(
            {
                "protocol_version": "1.0",
                "correlation_id": "x",
                "operation": "search",
                "ok": False,
                "result": {
                    "context": "",
                    "hits": [],
                    "result_count": 0,
                    "truncated": False,
                },
                "error": {
                    "code": "STORAGE_ERROR",
                    "message": "database locked",
                    "retryable": True,
                },
            }
        )
        assert response.ok is False
        assert response.result.context == ""
        assert response.result.result_count == 0
