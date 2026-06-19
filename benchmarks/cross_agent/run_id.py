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
    top_k: int,
    dataset_id: str | None = None,
    dataset_version: str | None = None,
    max_conversations: int | None = None,
) -> str:
    """Return a stable run id from benchmark matrix coordinates.

    All settings that can change query results must appear in the payload.
    """
    dataset_id_part = dataset_id or ""
    dataset_version_part = dataset_version or ""
    max_conv_part = "" if max_conversations is None else str(max_conversations)
    payload = (
        f"{family.value}|{agent.value}|{backend.value}|{seed}|{top_k}|"
        f"{dataset_id_part}|{dataset_version_part}|{max_conv_part}"
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return (
        f"{family.value}-{agent.value}-{backend.value}-s{seed}-k{top_k}-{digest}"
    )


def resolve_run_id(config: BenchmarkRunConfig) -> str:
    """Use explicit ``run_id`` or derive one from config fields."""
    if config.run_id:
        return config.run_id
    return derive_run_id(
        family=config.family,
        agent=config.agent,
        backend=config.backend,
        seed=config.seed,
        top_k=config.top_k,
        dataset_id=config.dataset_id,
        dataset_version=config.dataset_version,
        max_conversations=config.max_conversations,
    )
