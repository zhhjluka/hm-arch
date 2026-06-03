"""Public-behavior tests for HM-27 seven-layer facade integration."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hm_arch import HMArch, MemoryConfig


@pytest.fixture()
def mem() -> HMArch:
    instance = HMArch(db_path=":memory:")
    yield instance
    instance.close()


def test_hmarch_initializes_all_seven_layers(mem: HMArch) -> None:
    assert mem._l0 is not None
    assert mem._l1 is not None
    assert mem._l2 is not None
    assert mem._l3 is not None
    assert mem._l4 is not None
    assert mem._l5 is not None
    assert mem._l6 is not None


def test_add_populates_l0_sensory_register(mem: HMArch) -> None:
    assert mem._l0.size == 0
    mem.add("sensory event")
    assert mem._l0.size == 1
    contents = [item.content for item in mem._l0.snapshot()]
    assert "sensory event" in contents


def test_search_includes_l0_by_default(mem: HMArch) -> None:
    mem.add("unique sensory probe alpha")
    result = mem.search("sensory probe alpha", top_k=5)
    layers = {item.layer for item in result.results}
    assert 0 in layers
    assert result.source_breakdown.get(0, 0) >= 1


def test_l5_skills_via_facade_without_manual_layer(mem: HMArch) -> None:
    mem.store_skill("git_push", description="Push commits 推代码", code="git push")
    hit = mem.match_skill("推代码")
    assert hit is not None
    assert hit.name == "git_push"
    assert mem.list_skills()[0].name == "git_push"


def test_l6_policy_roundtrip_via_facade(mem: HMArch) -> None:
    mem.set_policy("consolidation_replay_ratio", "0.35")
    assert mem.get_policy("consolidation_replay_ratio") == "0.35"
    plan = mem.strategy_plan()
    assert plan.policies["consolidation_replay_ratio"] == "0.35"


def test_retrieval_top_k_multiplier_expands_results(mem: HMArch) -> None:
    for i in range(6):
        mem.add(f"expand probe item {i}")
    mem.set_policy("retrieval_top_k_multiplier", "1.0")
    baseline = mem.search("expand probe", top_k=3)
    mem.set_policy("retrieval_top_k_multiplier", "2.0")
    boosted = mem.search("expand probe", top_k=3)
    assert len(boosted.results) >= len(baseline.results)
    assert boosted.source_breakdown[2] >= baseline.source_breakdown[2]


def test_prefer_hot_memories_boosts_ranking(mem: HMArch) -> None:
    cold = mem.add("shared topic cold variant", importance=0.5)
    hot = mem.add("shared topic hot variant", importance=0.5)
    for _ in range(4):
        mem.search("hot variant", top_k=5)
    mem.set_policy("hot_access_threshold", "2")
    mem.set_policy("prefer_hot_memories", "true")
    boosted = mem.search("shared topic", top_k=5)
    mem.set_policy("prefer_hot_memories", "false")
    neutral = mem.search("shared topic", top_k=5)

    boosted_item = next(
        (item for item in boosted.results if item.memory_id == hot.memory_id),
        None,
    )
    neutral_item = next(
        (item for item in neutral.results if item.memory_id == hot.memory_id),
        None,
    )
    assert boosted_item is not None
    assert neutral_item is not None
    assert boosted_item.score > neutral_item.score
    assert cold.memory_id != hot.memory_id


def test_consolidation_replay_ratio_policy_applied(tmp_path: Path) -> None:
    cfg = MemoryConfig(
        db_path=str(tmp_path / "replay.db"),
        replay_sample_ratio=0.1,
    )
    mem = HMArch(config=cfg)
    try:
        for i in range(10):
            mem.add(f"User prefers Python lesson {i}", importance=0.8)
        mem.set_policy("consolidation_replay_ratio", "1.0")
        report = mem.consolidate()
        assert report.extracted_semantics >= 1
    finally:
        mem.close()


def test_get_stats_reports_l0_through_l6(mem: HMArch) -> None:
    mem.add("stats probe")
    mem.store_skill("deploy", description="release deploy")
    stats = mem.get_stats()
    for layer in range(7):
        assert layer in stats.by_layer
    assert stats.by_layer[0] >= 1
    assert stats.by_layer[2] >= 1
    assert stats.by_layer[5] == 1
    assert stats.by_layer[6] == 0
    assert stats.archive_storage_mb >= 0.0


def test_get_stats_l6_counts_persisted_policies(mem: HMArch) -> None:
    assert mem.get_stats().by_layer[6] == 0
    mem.set_policy("prefer_hot_memories", "true")
    stats = mem.get_stats()
    assert stats.by_layer[6] >= 1


def test_get_stats_archive_storage_after_l4_archive(tmp_path: Path) -> None:
    archive_root = tmp_path / "archives"
    cfg = MemoryConfig(
        db_path=str(tmp_path / "mem.db"),
        archive_root=str(archive_root),
        replay_sample_ratio=1.0,
    )
    mem = HMArch(config=cfg)
    try:
        receipt = mem.add("User prefers archived Python tutorials", importance=0.7)
        old_time = (
            datetime.now(tz=timezone.utc) - timedelta(days=60)
        ).isoformat()
        mem._db.execute(
            "UPDATE memory_index SET created_at = ? WHERE id = ?",
            (old_time, receipt.memory_id),
        )
        mem.consolidate()
        stats = mem.get_stats()
        assert stats.by_layer[4] >= 1
        assert stats.archive_storage_mb > 0.0
    finally:
        mem.close()


def test_l2_capacity_limit_enforced(mem: HMArch) -> None:
    cfg = MemoryConfig(db_path=":memory:", max_memories_l2=2)
    limited = HMArch(config=cfg)
    try:
        limited.add("one")
        limited.add("two")
        with pytest.raises(ValueError, match="max_memories_l2"):
            limited.add("three")
    finally:
        limited.close()


def test_l3_capacity_limit_enforced(mem: HMArch) -> None:
    cfg = MemoryConfig(db_path=":memory:", max_memories_l3=1)
    limited = HMArch(config=cfg)
    try:
        limited._l3.upsert("user", "likes", "Python")
        with pytest.raises(ValueError, match="max_memories"):
            limited._l3.upsert("team", "likes", "Java")
    finally:
        limited.close()


def test_l3_capacity_allows_superseding_replacement(mem: HMArch) -> None:
    cfg = MemoryConfig(db_path=":memory:", max_memories_l3=1)
    limited = HMArch(config=cfg)
    try:
        limited._l3.upsert("user", "likes", "Python")
        rust_id = limited._l3.upsert("user", "likes", "Rust")
        fact = limited._l3.get_by_entity_relation("user", "likes")
        assert fact is not None
        assert fact.memory_id == rust_id
        assert fact.value == "Rust"
        assert limited._l3.count(status="active") == 1
    finally:
        limited.close()


def test_l5_capacity_limit_via_facade(mem: HMArch) -> None:
    cfg = MemoryConfig(db_path=":memory:", max_skills_l5=2)
    limited = HMArch(config=cfg)
    try:
        limited.store_skill("alpha")
        limited.store_skill("beta")
        with pytest.raises(ValueError, match="max_skills"):
            limited.store_skill("gamma")
    finally:
        limited.close()
