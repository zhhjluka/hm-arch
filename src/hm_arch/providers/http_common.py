"""Shared HTTP helpers for optional remote providers (stdlib only)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class ProviderHTTPError(RuntimeError):
    """Raised when a provider HTTP call fails."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        provider: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.provider = provider


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    api_key: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """POST JSON and return the parsed response body."""
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise ProviderHTTPError(
            f"Provider request failed ({exc.code}): {detail}",
            status=exc.code,
        ) from exc
    except urllib.error.URLError as exc:
        raise ProviderHTTPError(f"Provider request failed: {exc}") from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderHTTPError("Provider returned non-JSON response") from exc


def chat_completion_text(
    response: dict[str, Any],
) -> str:
    """Extract assistant text from an OpenAI-compatible chat response."""
    try:
        return response["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, AttributeError) as exc:
        raise ProviderHTTPError("Unexpected chat completion response shape") from exc
