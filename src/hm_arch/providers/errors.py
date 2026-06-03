"""Exceptions raised by optional provider backends."""

from __future__ import annotations


class ProviderRuntimeError(RuntimeError):
    """Remote provider call failed and ``provider_fallback_to_local`` is disabled."""
