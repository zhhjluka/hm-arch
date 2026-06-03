"""Independent tests for HM-29 memory strength modulation."""

from __future__ import annotations

import pytest

from hm_arch import EventType, HMArch, MemoryConfig
from hm_arch.forgetting.strength import (
    apply_strength_to_retention,
    compute_initial_strength,
    consistency_modifier,
    emotion_modifier,
    importance_modifier,
    reinforcement_delta,
    repetition_modifier,
    score_local_emotion,
    score_local_importance,
)
from hm_arch.forgetting.time import ManualTimeProvider
from hm_arch.layers.l3_semantic import L3SemanticMemory
from hm_arch.storage.sqlite import SQLiteStore


class TestModifierFunctions:
    def test_importance_modifier_bounds(self):
        assert importance_modifier(0.0) == pytest.approx(-0.10)
        assert importance_modifier(0.5) == pytest.approx(0.0)
        assert importance_modifier(1.0) == pytest.approx(0.10)

    def test_emotion_modifier_bounds(self):
        assert emotion_modifier(0.0) == pytest.approx(-0.075)
        assert emotion_modifier(0.5) == pytest.approx(0.0)
        assert emotion_modifier(1.0) == pytest.approx(0.075)

    def test_repetition_modifier_caps(self):
        assert repetition_modifier(0) == pytest.approx(0.0)
        assert repetition_modifier(1) == pytest.approx(0.04)
        assert repetition_modifier(10) == pytest.approx(0.12)

    def test_consistency_modifier_values(self):
        assert consistency_modifier("neutral") == pytest.approx(0.0)
        assert consistency_modifier("consistent") == pytest.approx(0.08)
        assert consistency_modifier("conflict_new") == pytest.approx(0.0)


class TestLocalScoring:
    def test_error_event_raises_importance_and_emotion(self):
        content = "Disk failure on primary node"
        imp = score_local_importance(content, event_type=EventType.ERROR)
        emo = score_local_emotion(content, event_type=EventType.ERROR)
        assert imp > 0.5
        assert emo > 0.5

    def test_neutral_conversation_near_baseline(self):
        imp = score_local_importance(
            "routine status update", event_type=EventType.CONVERSATION
        )
        assert imp == pytest.approx(0.5, abs=0.15)


class TestRetentionScaling:
    def test_high_strength_decays_slower_than_low(self):
        layer_ret = 0.5
        high = apply_strength_to_retention(layer_ret, 1.0)
        low = apply_strength_to_retention(layer_ret, 0.6)
        assert high > low


class TestFacadeStrength:
    @pytest.fixture()
    def clock(self):
        return ManualTimeProvider()

    def test_receipt_reports_effective_importance_and_strength(self, clock):
        mem = HMArch(
            config=MemoryConfig(db_path=":memory:"),
            time_provider=clock,
        )
        try:
            receipt = mem.add(
                "CRITICAL: production outage must be fixed immediately!!!",
                event_type=EventType.ERROR,
                metadata={"critical": True},
            )
            assert 0.0 <= receipt.importance <= 1.0
            assert 0.25 <= receipt.initial_strength <= 1.0
            assert receipt.importance >= 0.5
            assert receipt.initial_strength >= 0.9
            assert "30d" in receipt.decay_estimate
        finally:
            mem.close()

    def test_explicit_importance_on_receipt(self, clock):
        mem = HMArch(
            config=MemoryConfig(db_path=":memory:"),
            time_provider=clock,
        )
        try:
            receipt = mem.add("minor note", importance=0.9)
            assert receipt.importance == pytest.approx(0.9)
            assert receipt.initial_strength == pytest.approx(1.0, abs=0.02)
        finally:
            mem.close()

    def test_repetition_increases_initial_strength(self, clock):
        mem = HMArch(
            config=MemoryConfig(db_path=":memory:"),
            time_provider=clock,
        )
        try:
            first = mem.add("User prefers Python", importance=0.0)
            second = mem.add("User prefers Python", importance=0.0)
            assert second.initial_strength > first.initial_strength
        finally:
            mem.close()

    def test_retrieval_reinforcement_boosts_stored_strength(self, clock):
        mem = HMArch(
            config=MemoryConfig(
                db_path=":memory:",
                retrieval_relevance_threshold=0.1,
            ),
            time_provider=clock,
        )
        try:
            receipt = mem.add(
                "User prefers Python",
                importance=0.0,
            )
            mem.search("User prefers Python", top_k=1)
            rows = mem._db.query(
                """
                SELECT initial_strength, current_retention
                FROM memory_index WHERE id = ?
                """,
                (receipt.memory_id,),
            )
            assert float(rows[0]["initial_strength"]) > receipt.initial_strength
            assert float(rows[0]["current_retention"]) >= receipt.initial_strength
        finally:
            mem.close()

    def test_high_strength_retains_more_after_decay(self, clock):
        from hm_arch.consolidation import ConsolidationEngine

        mem = HMArch(
            config=MemoryConfig(db_path=":memory:", replay_sample_ratio=1.0),
            time_provider=clock,
        )
        try:
            strong = mem.add(
                "CRITICAL production outage",
                event_type=EventType.ERROR,
                importance=1.0,
            )
            weak = mem.add("minor observation", importance=0.0)
            clock.advance(days=30)
            ConsolidationEngine(
                mem._db,
                mem._l2,
                mem._l3,
                config=mem._config,
                time_provider=clock,
            ).run_consolidation_cycle()
            rows = {
                r["id"]: float(r["current_retention"])
                for r in mem._db.query(
                    "SELECT id, current_retention FROM memory_index WHERE layer = 2"
                )
            }
            assert rows[strong.memory_id] > rows[weak.memory_id]
        finally:
            mem.close()


class TestSemanticConsistencyStrength:
    def test_consistent_reupsert_boosts_strength(self):
        db = SQLiteStore(":memory:").connect()
        db.initialize_schema()
        l3 = L3SemanticMemory(db)
        mid = l3.upsert("user", "prefers", "Python", importance=0.0)
        before = db.query(
            "SELECT initial_strength FROM memory_index WHERE id = ?", (mid,)
        )[0]["initial_strength"]
        l3.upsert("user", "prefers", "Python")
        after = db.query(
            "SELECT initial_strength FROM memory_index WHERE id = ?", (mid,)
        )[0]["initial_strength"]
        assert float(after) > float(before)
        db.close()

    def test_conflict_superseded_penalizes_old_fact(self):
        db = SQLiteStore(":memory:").connect()
        db.initialize_schema()
        l3 = L3SemanticMemory(db)
        old_id = l3.upsert("user", "prefers", "Python")
        old_retention = float(
            db.query(
                "SELECT current_retention FROM memory_index WHERE id = ?",
                (old_id,),
            )[0]["current_retention"]
        )
        l3.upsert("user", "prefers", "Rust")
        superseded = db.query(
            "SELECT current_retention FROM memory_index WHERE id = ?", (old_id,)
        )[0]["current_retention"]
        assert float(superseded) < old_retention
        db.close()


class TestReinforcementDelta:
    def test_reinforcement_is_deterministic_and_bounded(self):
        s, r = reinforcement_delta(
            initial_strength=0.8,
            current_retention=0.7,
            relevance=0.5,
            rate=0.06,
        )
        assert s > 0.8
        assert r > 0.7
        assert s <= 1.0
        assert r <= 1.0


class TestComputeInitialStrength:
    def test_default_neutral_is_one(self):
        assert compute_initial_strength(importance=0.5, emotion=0.5) == pytest.approx(
            1.0
        )
