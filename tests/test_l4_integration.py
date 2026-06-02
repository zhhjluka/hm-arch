"""Integration tests for L4 search and consolidation wiring (HM-19)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hm_arch import HMArch, MemoryConfig
from hm_arch.consolidation import ConsolidationEngine
from hm_arch.layers.l2_episodic import L2EpisodicBuffer
from hm_arch.layers.l3_semantic import L3SemanticMemory
from hm_arch.layers.l4_ltm import L4EpisodicLTM
from hm_arch.storage.sqlite import SQLiteStore


def _set_old_created_at(db: SQLiteStore, memory_id: str, days_ago: int) -> None:
    old_time = (datetime.now(tz=timezone.utc) - timedelta(days=days_ago)).isoformat()
    db.execute(
        "UPDATE memory_index SET created_at = ? WHERE id = ?",
        (old_time, memory_id),
    )


@pytest.fixture()
def hmarch_dirs(tmp_path: Path):
    """HMArch with isolated SQLite file and L4 root."""
    db_file = tmp_path / "mem.db"
    ltm_root = tmp_path / "ltm_data"
    cfg = MemoryConfig(db_path=str(db_file), ltm_root=str(ltm_root))
    memory = HMArch(config=cfg)
    yield memory, tmp_path
    memory.close()


def test_consolidate_archives_low_retention_l2(hmarch_dirs) -> None:
    memory, _ = hmarch_dirs
    receipt = memory.add("Ancient preference for COBOL", importance=0.6)
    _set_old_created_at(memory._db, receipt.memory_id, days_ago=90)

    report = memory.consolidate()

    assert report.archived_to_l4 >= 1
    rows = memory._db.query(
        "SELECT status, metadata FROM memory_index WHERE id = ?",
        (receipt.memory_id,),
    )
    assert rows[0]["status"] == "archived"
    meta = json.loads(rows[0]["metadata"])
    assert meta["source_l2_memory_id"] == receipt.memory_id
    assert "l4_archive_path" in meta
    assert memory._l4.retrieve(receipt.memory_id) is not None


def test_search_returns_archived_memory_with_layer_four(hmarch_dirs) -> None:
    memory, _ = hmarch_dirs
    receipt = memory.add("Archived Python episodic fact", importance=0.6)
    _set_old_created_at(memory._db, receipt.memory_id, days_ago=90)
    memory.consolidate()

    result = memory.search("Archived Python episodic", top_k=5)
    l4_hits = [item for item in result.results if item.layer == 4]
    assert l4_hits, "Expected L4 search hit for archived episodic memory"
    assert l4_hits[0].memory_id == receipt.memory_id
    assert l4_hits[0].metadata.get("source_l2_memory_id") == receipt.memory_id


def test_l4_ranks_below_active_l2_with_similar_relevance(hmarch_dirs) -> None:
    memory, _ = hmarch_dirs
    old = memory.add("Python tutorial notes from last year", importance=0.6)
    _set_old_created_at(memory._db, old.memory_id, days_ago=90)
    memory.consolidate()

    memory.add("Python tutorial notes fresh edition", importance=0.8)
    result = memory.search("Python tutorial notes", top_k=5)

    layers = [item.layer for item in result.results if "Python tutorial" in item.content]
    assert 2 in layers
    assert 4 in layers
    l2_item = next(item for item in result.results if item.layer == 2)
    l4_item = next(item for item in result.results if item.layer == 4)
    assert l2_item.score > l4_item.score


def test_archived_memory_not_in_active_l2_count(hmarch_dirs) -> None:
    memory, _ = hmarch_dirs
    receipt = memory.add("Will be archived", importance=0.5)
    assert memory._l2.count() == 1
    _set_old_created_at(memory._db, receipt.memory_id, days_ago=90)
    memory.consolidate()
    assert memory._l2.count() == 0


def test_consolidation_engine_archives_without_hmarch(tmp_path: Path) -> None:
    db = SQLiteStore(":memory:").connect()
    db.initialize_schema()
    l2 = L2EpisodicBuffer(db)
    l3 = L3SemanticMemory(db)
    l4 = L4EpisodicLTM(tmp_path / "ltm")
    cfg = MemoryConfig(replay_sample_ratio=1.0)
    engine = ConsolidationEngine(db, l2, l3, l4=l4, config=cfg)

    mid = l2.encode("Stale episodic detail", importance=0.5)
    _set_old_created_at(db, mid, days_ago=90)
    report = engine.run_consolidation_cycle()

    assert report.archived_to_l4 == 1
    archived = l4.retrieve(mid)
    assert archived is not None
    assert archived.metadata["source_l2_memory_id"] == mid


def test_l4_search_on_isolated_store(tmp_path: Path) -> None:
    l4 = L4EpisodicLTM(tmp_path)
    l4.archive(
        "mid-1",
        "vector database indexing",
        retention=0.1,
        importance=0.5,
        metadata={"source_l2_memory_id": "mid-1"},
    )
    hits = l4.search("vector database", top_k=3)
    assert len(hits) == 1
    assert hits[0][0].memory_id == "mid-1"
    assert hits[0][1] > 0.0
