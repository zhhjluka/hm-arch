"""Deterministic run identifier generation."""

from __future__ import annotations

import hashlib

from .types import AgentKind, BenchmarkFamily, BenchmarkRunConfig, MemoryBackendKind


def derive_run_id(
    *,
    family: BenchmarkFamily,
    agent: AgentKind,
    backend: MemoryBackendKind,
    seed: int,
) -> str:
    """Return a stable run id from benchmark matrix coordinates."""
    payload = f"{family.value}|{agent.value}|{backend.value}|{seed}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{family.value}-{agent.value}-{backend.value}-s{seed}-{digest}"


def resolve_run_id(config: BenchmarkRunConfig) -> str:
    """Use explicit ``run_id`` or derive one from config fields."""
    if config.run_id:
        return config.run_id
    return derive_run_id(
        family=config.family,
        agent=config.agent,
        backend=config.backend,
        seed=config.seed,
    )
