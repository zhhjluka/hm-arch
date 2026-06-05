"""Offline runtime handlers for HM-Arch adapter CLI commands."""

from __future__ import annotations

from hm_arch.integrations.common import (
    build_turn_start_context,
    record_turn_end,
    run_idle_consolidation,
)
from hm_arch.integrations.config import IntegrationConfig
from hm_arch.integrations.storage_router import MemoryStoreRouter
from hm_arch.integrations.protocol import (
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
)


def _integration_config() -> IntegrationConfig:
    return IntegrationConfig()


def execute_recall(request: RecallRequest) -> RecallResponse:
    """Run recall and return a stable adapter response (fail-open on errors)."""
    config = _integration_config()
    top_k = request.top_k or config.recall_top_k
    try:
        router = MemoryStoreRouter(config)
        hits = router.search(request.task, top_k=top_k)
        with router.open() as memory:
            context = build_turn_start_context(
                memory,
                request.task,
                top_k=top_k,
                hits=hits,
            )
            truncated = len(context) > config.max_context_chars
            if truncated:
                context = context[: config.max_context_chars]
            return RecallResponse(
                ok=True,
                context=context,
                result_count=len(hits.results),
                truncated=truncated,
                error=None,
            )
    except Exception as exc:  # noqa: BLE001 — adapter must fail open
        return fail_open_recall(str(exc))


def execute_record(request: RecordRequest) -> RecordResponse:
    """Run record and return a stable adapter response (fail-open on errors)."""
    config = _integration_config()
    try:
        with MemoryStoreRouter(config).open_for_write() as memory:
            memory_ids = record_turn_end(
                memory,
                request.user_message,
                request.agent_message,
            )
            return RecordResponse(
                ok=True,
                memory_ids=memory_ids,
                recorded_count=len(memory_ids),
                error=None,
            )
    except Exception as exc:  # noqa: BLE001 — adapter must fail open
        return fail_open_record(str(exc))


def execute_consolidate(_request: ConsolidateRequest) -> ConsolidateResponse:
    """Run consolidate and return a stable adapter response (fail-open on errors)."""
    config = _integration_config()
    try:
        with MemoryStoreRouter(config).open_for_write() as memory:
            report = run_idle_consolidation(memory)
            return ConsolidateResponse(
                ok=True,
                extracted_semantics=report.extracted_semantics,
                merged_duplicates=report.merged_duplicates,
                scheduled_reviews=report.scheduled_reviews,
                archived_to_l4=report.archived_to_l4,
                error=None,
            )
    except Exception as exc:  # noqa: BLE001 — adapter must fail open
        return fail_open_consolidate(str(exc))


def dispatch_adapter_request(
    operation: str,
    payload: dict,
) -> RecallResponse | RecordResponse | ConsolidateResponse:
    """Parse *payload* for *operation* and execute the matching handler."""
    envelope = dict(payload)
    envelope.setdefault("operation", operation)
    if envelope.get("operation") != operation:
        return _fail_open_for_operation(
            operation,
            f"operation {envelope['operation']!r} does not match command {operation!r}",
        )
    try:
        request = _parse_request_for_operation(operation, envelope)
    except ProtocolValidationError as exc:
        return _fail_open_for_operation(operation, str(exc))
    except TypeError as exc:
        return _fail_open_for_operation(operation, str(exc))

    if operation == "recall":
        assert isinstance(request, RecallRequest)
        return execute_recall(request)
    if operation == "record":
        assert isinstance(request, RecordRequest)
        return execute_record(request)
    assert isinstance(request, ConsolidateRequest)
    return execute_consolidate(request)


def _parse_request_for_operation(
    operation: str,
    envelope: dict,
) -> RecallRequest | RecordRequest | ConsolidateRequest:
    from hm_arch.integrations.protocol import parse_adapter_request

    parsed = parse_adapter_request(envelope)
    if operation == "recall" and not isinstance(parsed, RecallRequest):
        raise ProtocolValidationError("expected recall request")
    if operation == "record" and not isinstance(parsed, RecordRequest):
        raise ProtocolValidationError("expected record request")
    if operation == "consolidate" and not isinstance(parsed, ConsolidateRequest):
        raise ProtocolValidationError("expected consolidate request")
    return parsed


def _fail_open_for_operation(
    operation: str,
    error: str,
) -> RecallResponse | RecordResponse | ConsolidateResponse:
    if operation == "recall":
        return fail_open_recall(error)
    if operation == "record":
        return fail_open_record(error)
    return fail_open_consolidate(error)
