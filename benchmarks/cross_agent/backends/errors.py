"""Shared errors for memory backend adapters."""

from __future__ import annotations


class ProviderPackageRequired(ImportError):
    """Raised when an optional provider package is required but not installed."""
