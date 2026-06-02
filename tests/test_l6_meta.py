"""Tests for L6MetaMemory.

Coverage
--------
Construction
* Layer index is 6.

track_access()
* Increments memory_index.access_count and sets last_accessed_at.
* Updates meta_memory per (memory_id, layer) and layer totals.
* Works when memory_id is not in memory_index (meta-only).
* Empty memory_id raises ValueError.
* Negative layer raises ValueError.

get_hot_memories()
* Returns memories ordered by access_count descending.
* Respects limit and optional layer filter.
* Invalid limit raises ValueError.

set_policy() / get_policy()
* Persists custom values in meta_memory.
* Defaults apply when policy not set.

strategy_plan()
* Returns policies, recommendations, and layer totals.
* Recommendations mention hot memories when threshold met.

Integration
* HMArch.search() records access for returned results.

Persistence
* Access counts and policies survive DB close and reopen.

Importability
* L6 types importable from hm_arch.layers.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from hm_arch import HMArch
from hm_arch.layers import HotMemoryRecord, L6MetaMemory, StrategyPlan
from hm_arch.layers.l2_episodic import L2EpisodicBuffer
from hm_arch.storage.sqlite import SQLiteStore


def _make_db(path: str = ":memory:") -> SQLiteStore:
    db = SQLiteStore(path)
    db.connect()
    db.initialize_schema()
    return db


def _make_l6(path: str = ":memory:") -> L6MetaMemory:
    return L6MetaMemory(_make_db(path))


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_layer_index_is_six() -> None:
    assert L6MetaMemory.LAYER_INDEX == 6


# ---------------------------------------------------------------------------
# track_access
# ---------------------------------------------------------------------------


def test_track_access_updates_memory_index() -> None:
    db = _make_db()
    l2 = L2EpisodicBuffer(db)
    l6 = L6MetaMemory(db)
    mid = l2.encode("hello episodic")

    l6.track_access(mid, layer=2)
    l6.track_access(mid, layer=2)

    rows = db.query(
        "SELECT access_count, last_accessed_at FROM memory_index WHERE id = ?",
        (mid,),
    )
    assert int(rows[0]["access_count"]) == 2
    assert rows[0]["last_accessed_at"] is not None


def test_track_access_updates_meta_counters() -> None:
    db = _make_db()
    l2 = L2EpisodicBuffer(db)
    l6 = L6MetaMemory(db)
    mid = l2.encode("count me")

    l6.track_access(mid, layer=2)

    pair_rows = db.query(
        "SELECT value FROM meta_memory WHERE key = ?",
        (f"hm_arch.l6.access.{mid}.2",),
    )
    assert int(pair_rows[0]["value"]) == 1

    layer_rows = db.query(
        "SELECT value FROM meta_memory WHERE key = ?",
        ("hm_arch.l6.layer_total.2",),
    )
    assert int(layer_rows[0]["value"]) == 1


def test_track_access_without_memory_index_row() -> None:
    db = _make_db()
    l6 = L6MetaMemory(db)
    ghost_id = "not-in-index-abc"

    l6.track_access(ghost_id, layer=1)

    rows = db.query(
        "SELECT value FROM meta_memory WHERE key = ?",
        (f"hm_arch.l6.access.{ghost_id}.1",),
    )
    assert int(rows[0]["value"]) == 1
    index_rows = db.query(
        "SELECT id FROM memory_index WHERE id = ?", (ghost_id,)
    )
    assert index_rows == []


def test_track_access_empty_memory_id_raises() -> None:
    l6 = _make_l6()
    with pytest.raises(ValueError, match="memory_id"):
        l6.track_access("", layer=2)


def test_track_access_negative_layer_raises() -> None:
    l6 = _make_l6()
    with pytest.raises(ValueError, match="layer"):
        l6.track_access("abc", layer=-1)


# ---------------------------------------------------------------------------
# get_hot_memories
# ---------------------------------------------------------------------------


def test_get_hot_memories_descending_order() -> None:
    db = _make_db()
    l2 = L2EpisodicBuffer(db)
    l6 = L6MetaMemory(db)

    mid_a = l2.encode("memory a")
    mid_b = l2.encode("memory b")
    mid_c = l2.encode("memory c")

    for _ in range(3):
        l6.track_access(mid_a, layer=2)
    for _ in range(1):
        l6.track_access(mid_b, layer=2)
    for _ in range(5):
        l6.track_access(mid_c, layer=2)

    hot = l6.get_hot_memories(limit=10)
    assert [h.memory_id for h in hot] == [mid_c, mid_a, mid_b]
    assert hot[0].access_count == 5
    assert isinstance(hot[0], HotMemoryRecord)


def test_get_hot_memories_layer_filter() -> None:
    db = _make_db()
    l2 = L2EpisodicBuffer(db)
    l6 = L6MetaMemory(db)
    mid = l2.encode("l2 only")
    l6.track_access(mid, layer=2)
    l6.track_access(mid, layer=2)

    hot = l6.get_hot_memories(limit=5, layer=3)
    assert hot == []


def test_get_hot_memories_invalid_limit_raises() -> None:
    l6 = _make_l6()
    with pytest.raises(ValueError, match="limit"):
        l6.get_hot_memories(limit=0)


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


def test_set_policy_persists() -> None:
    l6 = _make_l6()
    l6.set_policy("consolidation_replay_ratio", "0.35")
    assert l6.get_policy("consolidation_replay_ratio") == "0.35"


def test_get_policy_uses_defaults() -> None:
    l6 = _make_l6()
    assert l6.get_policy("retrieval_top_k_multiplier") == "1.0"
    assert l6.get_policy("hot_access_threshold") == "3"


def test_policy_persists_across_reopen() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "meta.db")
        db = _make_db(db_path)
        l6 = L6MetaMemory(db)
        l6.set_policy("prefer_hot_memories", "true")
        db.close()

        db2 = SQLiteStore(db_path)
        db2.connect()
        l6b = L6MetaMemory(db2)
        assert l6b.get_policy("prefer_hot_memories") == "true"
        db2.close()


# ---------------------------------------------------------------------------
# strategy_plan
# ---------------------------------------------------------------------------


def test_strategy_plan_returns_structure() -> None:
    l6 = _make_l6()
    plan = l6.strategy_plan()
    assert isinstance(plan, StrategyPlan)
    assert "consolidation_replay_ratio" in plan.policies
    assert isinstance(plan.recommendations, list)
    assert len(plan.recommendations) >= 1


def test_strategy_plan_hot_recommendation() -> None:
    db = _make_db()
    l2 = L2EpisodicBuffer(db)
    l6 = L6MetaMemory(db)
    l6.set_policy("hot_access_threshold", "2")
    mid = l2.encode("popular")
    for _ in range(3):
        l6.track_access(mid, layer=2)

    plan = l6.strategy_plan()
    assert plan.hot_memory_count >= 1
    assert any("hot access threshold" in r.lower() for r in plan.recommendations)


# ---------------------------------------------------------------------------
# HMArch integration
# ---------------------------------------------------------------------------


def test_search_records_access_for_results() -> None:
    mem = HMArch(db_path=":memory:")
    receipt = mem.add("Python rocks")
    mem.search("Python", top_k=5)

    rows = mem._db.query(
        "SELECT access_count FROM memory_index WHERE id = ?",
        (receipt.memory_id,),
    )
    assert int(rows[0]["access_count"]) >= 1
    mem.close()


def test_search_empty_does_not_increment_access() -> None:
    mem = HMArch(db_path=":memory:")
    mem.search("nothing here")
    rows = mem._db.query("SELECT SUM(access_count) AS total FROM memory_index")
    total = rows[0]["total"]
    assert total is None or int(total) == 0
    mem.close()


def test_access_counts_persist_across_reopen() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "persist.db")
        mem = HMArch(db_path=db_path)
        receipt = mem.add("sticky memory")
        mem.search("sticky", top_k=5)
        mem.close()

        mem2 = HMArch(db_path=db_path)
        rows = mem2._db.query(
            "SELECT access_count FROM memory_index WHERE id = ?",
            (receipt.memory_id,),
        )
        assert int(rows[0]["access_count"]) >= 1
        mem2.close()


# ---------------------------------------------------------------------------
# Importability
# ---------------------------------------------------------------------------


def test_import_from_layers_package() -> None:
    from hm_arch.layers import HotMemoryRecord, L6MetaMemory, StrategyPlan

    assert L6MetaMemory.LAYER_INDEX == 6
    assert HotMemoryRecord is not None
    assert StrategyPlan is not None
