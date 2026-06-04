"""Fail-open error responses for agent adapters.

Fail-open contract
------------------
Agent hooks and CLIs must never block the host agent when HM-Arch fails.
Callers always receive a JSON-serializable dict:

* ``ok: true`` — operation completed (possibly with empty recall context).
* ``ok: false`` — HM-Arch could not complete the request; the host should log
  ``message`` and continue. No exception is required at the host boundary when
  using :func:`~hm_arch.integrations.executor.execute_adapter_request`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

FAIL_OPEN_ERROR_CODES = frozenset(
    {
        "INVALID_PAYLOAD",
        "UNSUPPORTED_OPERATION",
        "INVALID_CONFIG",
        "MEMORY_ERROR",
    }
)


@dataclass
class AdapterFailOpenResponse:
    """Structured failure returned instead of raising through host boundaries."""

    ok: bool
    operation: str
    error_code: str
    message: str
    detail: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.ok:
            raise ValueError("AdapterFailOpenResponse must have ok=False")
        if self.error_code not in FAIL_OPEN_ERROR_CODES:
            raise ValueError(
                f"Unknown error_code {self.error_code!r}. "
                f"Valid codes: {sorted(FAIL_OPEN_ERROR_CODES)}"
            )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload["detail"] is None:
            del payload["detail"]
        return payload


def fail_open_response(
    operation: str,
    *,
    error_code: str,
    message: str,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a fail-open JSON response dict."""
    return AdapterFailOpenResponse(
        ok=False,
        operation=operation,
        error_code=error_code,
        message=message,
        detail=detail,
    ).to_dict()
