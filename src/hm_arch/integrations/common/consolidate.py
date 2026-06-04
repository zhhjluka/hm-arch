"""Idle consolidation helpers for agent hooks."""

from __future__ import annotations

from hm_arch import HMArch
from hm_arch.types import ConsolidationReport


def run_idle_consolidation(memory: HMArch) -> ConsolidationReport:
    """Run offline sleep consolidation (safe on an empty store)."""
    return memory.consolidate()
