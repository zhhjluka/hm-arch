"""Fixture resolution for cross-agent benchmark runs."""

from __future__ import annotations

from ..types import BenchmarkFamily, BenchmarkRunConfig, SyntheticFixture
from .locomo.loader import load_locomo_fixture
from .synthetic import get_synthetic_fixture


def resolve_fixture(config: BenchmarkRunConfig) -> SyntheticFixture:
    """Return the ingest/query fixture for *config*."""
    if config.family is BenchmarkFamily.LOCOMO and config.dataset_id:
        return load_locomo_fixture(
            config.dataset_id,
            config.dataset_version,
            max_conversations=config.max_conversations,
        )
    return get_synthetic_fixture(config.family)
