"""Parse real agent CLI stdout into benchmark answer payloads."""

from __future__ import annotations

import json
from typing import Any

from ..metrics import approximate_token_count


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_codex_exec_jsonl(stdout: str, *, prompt_text: str = "") -> dict[str, Any]:
    """Extract final agent message and usage from ``codex exec --json`` JSONL."""
    answer_parts: list[str] = []
    usage: dict[str, Any] | None = None
    for line in stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            event = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type == "turn.completed":
            raw_usage = event.get("usage")
            if isinstance(raw_usage, dict):
                usage = raw_usage
            continue
        if event_type != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        if item.get("type") != "agent_message":
            continue
        message = item.get("text") or item.get("content")
        if isinstance(message, str) and message.strip():
            answer_parts.append(message.strip())

    answer = answer_parts[-1] if answer_parts else ""
    input_tokens = _coerce_int(usage.get("input_tokens") if usage else None)
    output_tokens = _coerce_int(usage.get("output_tokens") if usage else None)
    if output_tokens is None and usage:
        reasoning = _coerce_int(usage.get("reasoning_output_tokens"))
        base_output = _coerce_int(usage.get("output_tokens"))
        if base_output is not None and reasoning is not None:
            output_tokens = base_output + reasoning

    payload: dict[str, Any] = {
        "answer": answer,
        "runner": "codex-exec-jsonl",
    }
    if input_tokens is not None:
        payload["input_tokens"] = input_tokens
        payload["input_token_source"] = "exact"
    else:
        payload["input_tokens"] = approximate_token_count(prompt_text)
        payload["input_token_source"] = "estimated"
    if output_tokens is not None:
        payload["output_tokens"] = output_tokens
        payload["output_token_source"] = "exact"
    else:
        payload["output_tokens"] = approximate_token_count(answer)
        payload["output_token_source"] = "estimated"
    if usage:
        payload["usage"] = usage
    return payload


def parse_claude_json_output(stdout: str, *, prompt_text: str = "") -> dict[str, Any]:
    """Parse ``claude -p ... --output-format json`` stdout."""
    text = stdout.strip()
    if not text:
        raise ValueError("empty stdout")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("claude JSON must be an object")

    answer = payload.get("result") or payload.get("answer") or text
    usage = payload.get("usage")
    input_tokens: int | None = None
    output_tokens: int | None = None
    if isinstance(usage, dict):
        input_tokens = _coerce_int(
            usage.get("input_tokens")
            or usage.get("inputTokens")
            or usage.get("prompt_tokens")
        )
        output_tokens = _coerce_int(
            usage.get("output_tokens")
            or usage.get("outputTokens")
            or usage.get("completion_tokens")
        )
    if input_tokens is None:
        input_tokens = _coerce_int(payload.get("input_tokens"))
    if output_tokens is None:
        output_tokens = _coerce_int(payload.get("output_tokens"))

    result: dict[str, Any] = {
        "answer": str(answer),
        "runner": "claude-json",
    }
    if input_tokens is not None:
        result["input_tokens"] = input_tokens
        result["input_token_source"] = "exact"
    else:
        result["input_tokens"] = approximate_token_count(prompt_text)
        result["input_token_source"] = "estimated"
    if output_tokens is not None:
        result["output_tokens"] = output_tokens
        result["output_token_source"] = "exact"
    else:
        result["output_tokens"] = approximate_token_count(str(answer))
        result["output_token_source"] = "estimated"
    if isinstance(usage, dict):
        result["usage"] = usage
    return result


def parse_openclaw_agent_json(stdout: str, *, prompt_text: str = "") -> dict[str, Any]:
    """Parse ``openclaw agent --json`` stdout."""
    text = stdout.strip()
    if not text:
        raise ValueError("empty stdout")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("openclaw agent JSON must be an object")

    answer = (
        payload.get("reply")
        or payload.get("message")
        or payload.get("result")
        or payload.get("text")
        or payload.get("answer")
        or text
    )
    usage = payload.get("usage")
    input_tokens: int | None = None
    output_tokens: int | None = None
    if isinstance(usage, dict):
        input_tokens = _coerce_int(usage.get("input_tokens") or usage.get("inputTokens"))
        output_tokens = _coerce_int(usage.get("output_tokens") or usage.get("outputTokens"))

    result: dict[str, Any] = {
        "answer": str(answer),
        "runner": "openclaw-agent-json",
    }
    if input_tokens is not None:
        result["input_tokens"] = input_tokens
        result["input_token_source"] = "exact"
    else:
        result["input_tokens"] = approximate_token_count(prompt_text)
        result["input_token_source"] = "estimated"
    if output_tokens is not None:
        result["output_tokens"] = output_tokens
        result["output_token_source"] = "exact"
    else:
        result["output_tokens"] = approximate_token_count(str(answer))
        result["output_token_source"] = "estimated"
    if isinstance(usage, dict):
        result["usage"] = usage
    return result
