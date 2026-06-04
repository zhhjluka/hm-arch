"""Stdin/stdout helpers for the HM-Arch adapter CLI."""

from __future__ import annotations

import dataclasses
import json
import sys
from typing import Any

from hm_arch.integrations.protocol import (
    ConsolidateResponse,
    RecallResponse,
    RecordResponse,
)


class InvalidAdapterPayloadError(ValueError):
    """Raised when stdin contains valid JSON that is not an adapter request object."""


def read_adapter_payload() -> dict[str, Any]:
    """Read a JSON adapter request object from stdin.

    Returns an empty dict when stdin is a TTY or contains no input, matching
    hook adapters so callers can rely on subcommand defaults.
    """
    if sys.stdin.isatty():
        return {}
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise InvalidAdapterPayloadError("adapter request must be a JSON object")
    return data


def emit_adapter_response(
    response: RecallResponse | RecordResponse | ConsolidateResponse,
) -> None:
    """Write a stable JSON adapter response to stdout."""
    print(json.dumps(dataclasses.asdict(response), ensure_ascii=False))
