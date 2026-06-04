"""Shared offline execution for agent adapter protocol requests."""

from __future__ import annotations

from hm_arch import EventType, HMArch
from hm_arch.types import ConsolidationReport

from .config import IntegrationConfig
from .errors import fail_open_response
from .protocol import (
    AdapterRequest,
    ConsolidateRequest,
    ConsolidateResponse,
    ProtocolValidationError,
    RecallRequest,
    RecallResponse,
    RecordRequest,
    RecordResponse,
    operation_from_payload,
    parse_adapter_request,
)


def _format_recall_context(
    memory: HMArch,
    task: str,
    *,
    top_k: int,
    max_context_chars: int,
) -> tuple[str, int, bool]:
    task = task.strip()
    if not task:
        return "", 0, False

    hits = memory.search(task, top_k=top_k)
    if not hits.results:
        return "", 0, False

    lines = ["## HM-Arch memory context", ""]
    for index, item in enumerate(hits.results, start=1):
        lines.append(
            f"{index}. [L{item.layer}] {item.content} "
            f"(retention={item.retention:.2f}, score={item.score:.2f})"
        )
    context = "\n".join(lines)
    truncated = False
    if max_context_chars >= 0 and len(context) > max_context_chars:
        context = context[: max_context_chars - 3].rstrip() + "..."
        truncated = True
    return context, len(hits.results), truncated


def _record_turn(
    memory: HMArch,
    user_message: str,
    agent_message: str,
) -> list[str]:
    recorded: list[str] = []
    user_message = user_message.strip()
    agent_message = agent_message.strip()

    if user_message:
        receipt = memory.add(
            f"User: {user_message}",
            event_type=EventType.CONVERSATION,
            importance=0.7,
        )
        recorded.append(receipt.memory_id)

    if agent_message:
        receipt = memory.add(
            f"Assistant: {agent_message}",
            event_type=EventType.CONVERSATION,
            importance=0.6,
        )
        recorded.append(receipt.memory_id)

    return recorded


def _consolidation_to_response(
    report: ConsolidationReport | None,
    *,
    skipped: bool,
) -> ConsolidateResponse:
    if report is None:
        return ConsolidateResponse(skipped=skipped)
    return ConsolidateResponse(
        skipped=skipped,
        extracted_semantics=report.extracted_semantics,
        merged_duplicates=report.merged_duplicates,
        resolved_conflicts=report.resolved_conflicts,
        archived_to_l4=report.archived_to_l4,
        scheduled_reviews=report.scheduled_reviews,
        marked_deletable=report.marked_deletable,
        duration_seconds=report.duration_seconds,
    )


def execute_typed_request(
    request: AdapterRequest,
    config: IntegrationConfig,
) -> dict:
    """Execute a validated request and return a success response dict."""
    memory_config = config.to_memory_config()
    with HMArch(config=memory_config) as memory:
        if isinstance(request, RecallRequest):
            top_k = request.top_k if request.top_k is not None else config.recall_top_k
            context, hit_count, truncated = _format_recall_context(
                memory,
                request.task,
                top_k=top_k,
                max_context_chars=config.max_context_chars,
            )
            return RecallResponse(
                context=context,
                hit_count=hit_count,
                truncated=truncated,
            ).to_dict()

        if isinstance(request, RecordRequest):
            memory_ids = _record_turn(
                memory,
                request.user_message,
                request.agent_message,
            )
            return RecordResponse(memory_ids=memory_ids).to_dict()

        assert isinstance(request, ConsolidateRequest)
        if not config.consolidation_enabled:
            return _consolidation_to_response(None, skipped=True).to_dict()
        report = memory.consolidate()
        return _consolidation_to_response(report, skipped=False).to_dict()


def execute_adapter_request(
    payload: dict,
    config: IntegrationConfig | None = None,
) -> dict:
    """Parse, execute, and always return a JSON-serializable response (fail-open).

    Malformed payloads and runtime failures yield ``ok: false`` responses so
    host agents can continue without handling exceptions.
    """
    cfg = config or IntegrationConfig()
    operation = operation_from_payload(payload)

    try:
        cfg.validate()
    except ValueError as exc:
        return fail_open_response(
            operation,
            error_code="INVALID_CONFIG",
            message=str(exc),
        )

    try:
        request = parse_adapter_request(payload)
    except ProtocolValidationError as exc:
        return fail_open_response(
            operation,
            error_code="INVALID_PAYLOAD",
            message=str(exc),
        )

    try:
        return execute_typed_request(request, cfg)
    except Exception as exc:  # noqa: BLE001 — fail-open boundary for host agents
        return fail_open_response(
            operation_from_payload(request),
            error_code="MEMORY_ERROR",
            message=str(exc) or "HM-Arch memory operation failed",
        )
