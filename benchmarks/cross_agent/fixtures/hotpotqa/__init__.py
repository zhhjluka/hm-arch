"""Versioned HotpotQA offline subsets."""

from .loader import (
    HOTPOTQA_SUBSET_VERSION,
    compute_subset_hash,
    get_hotpotqa_fixture,
    load_hotpotqa_config,
    load_hotpotqa_subset,
)

__all__ = [
    "HOTPOTQA_SUBSET_VERSION",
    "compute_subset_hash",
    "get_hotpotqa_fixture",
    "load_hotpotqa_config",
    "load_hotpotqa_subset",
]
