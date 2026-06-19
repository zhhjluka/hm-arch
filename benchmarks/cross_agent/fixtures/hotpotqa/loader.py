"""Load versioned HotpotQA offline subsets into harness fixtures."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from ...types import BenchmarkFamily, BenchmarkQuery, IngestItem, SyntheticFixture

HOTPOTQA_SUBSET_VERSION = "v1"
_FIXTURE_ROOT = Path(__file__).resolve().parent


def _version_dir(version: str = HOTPOTQA_SUBSET_VERSION) -> Path:
    return _FIXTURE_ROOT / version


def load_hotpotqa_config(version: str = HOTPOTQA_SUBSET_VERSION) -> dict[str, Any]:
    path = _version_dir(version) / "config.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_hotpotqa_subset(version: str = HOTPOTQA_SUBSET_VERSION) -> dict[str, Any]:
    config = load_hotpotqa_config(version)
    subset_path = _version_dir(version) / str(config["subset_file"])
    return json.loads(subset_path.read_text(encoding="utf-8"))


def compute_subset_hash(version: str = HOTPOTQA_SUBSET_VERSION) -> str:
    """Stable SHA-256 digest of the pinned subset JSON payload."""
    subset_path = _version_dir(version) / "subset.json"
    payload = subset_path.read_bytes()
    return hashlib.sha256(payload).hexdigest()


@lru_cache(maxsize=1)
def get_hotpotqa_fixture(version: str = HOTPOTQA_SUBSET_VERSION) -> SyntheticFixture:
    subset = load_hotpotqa_subset(version)
    ingest_items = tuple(
        IngestItem(
            item_id=str(doc["item_id"]),
            content=str(doc["content"]),
            metadata=dict(doc.get("metadata", {})),
        )
        for doc in subset["documents"]
    )
    queries = tuple(
        BenchmarkQuery(
            query_id=str(query["query_id"]),
            question=str(query["question"]),
            expected_answer=str(query["expected_answer"]),
            expected_memory_ids=tuple(str(mid) for mid in query["expected_memory_ids"]),
            supporting_facts=tuple(str(mid) for mid in query.get("supporting_facts", ())),
        )
        for query in subset["queries"]
    )
    return SyntheticFixture(
        family=BenchmarkFamily.HOTPOTQA,
        ingest_items=ingest_items,
        queries=queries,
        consolidate_after_ingest=True,
    )
