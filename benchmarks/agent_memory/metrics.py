"""Timing helpers for benchmark memory backends."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def measure_ms(operation: Callable[[], T]) -> tuple[T, float]:
    """Run *operation* and return its result plus elapsed milliseconds."""
    started = time.perf_counter()
    result = operation()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return result, elapsed_ms
