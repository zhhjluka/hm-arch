"""Independent tests for HM-29 memory strength modulation (PRD model)."""

from __future__ import annotations

import json

import pytest

from hm_arch import EventType, HMArch, MemoryConfig
from hm_arch.config import MemoryConfig as MemoryConfigCls
from hm_arch.forgetting.strength import (
    CONSISTENCY_MOD_MAX,
    CONSISTENCY_MOD_MIN,
    EMOTION_MOD_MAX,
    EMOTION_MOD_MIN,
    IMPORTANCE_MOD_MAX,
    IMPORTANCE_MOD_MIN,
    PRD_STRENGTH_MAX,
    REPETITION_MOD_MAX,
    REPETITION_MOD_MIN,
    STRENGTH_BASE,
    StrengthFactors,
    apply_retrieval_reinforcement,
    apply_strength_to_retention,
    compute_initial_strength,
    consistency_modifier_factor,
    emotion_modifier_factor,
    importance_modifier_factor,
    repetition_modifier_factor,
    score_local_emotion,
    score_local_importance,
)
from hm_arch.forgetting.time import ManualTimeProvider
from hm_arch.layers.l3_semantic import L3SemanticMemory
from hm_arch.storage.sqlite import SQLiteStore


class TestPrdModifierBounds:
    def test_importance_modifier_factor_bounds(self):
        assert importance_modifier_factor(0.0) == pytest.approx(IMPORTANCE_MOD_MIN)
        assert importance_modifier_factor(1.0) == pytest.approx(IMPORTANCE_MOD_MAX)
        assert importance_modifier_factor(0.5) == pytest.approx(1.5)

    def test_emotion_modifier_factor_bounds(self):
        assert emotion_modifier_factor(0.0) == pytest.approx(EMOTION_MOD_MIN)
        assert emotion_modifier_factor(1.0) == pytest.approx(EMOTION_MOD_MAX)
        assert emotion_modifier_factor(0.5) == pytest.approx(1.15)

    def test_repetition_modifier_factor_bounds(self):
        assert repetition_modifier_factor() == pytest.approx(REPETITION_MOD_MIN)
        assert repetition_modifier_factor(successful_retrievals=1) == pytest.approx(
            1.3
        )
        assert repetition_modifier_factor(successful_retrievals=10) == pytest.approx(
            REPETITION_MOD_MAX
        )

    def test_consistency_modifier_factor_bounds(self):
        assert consistency_modifier_factor("neutral") == pytest.approx(1.0)
        assert consistency_modifier_factor("consistent") == pytest.approx(
            CONSISTENCY_MOD_MAX
        )
        assert consistency_modifier_factor("conflict_superseded") == pytest.approx(
            CONSISTENCY_MOD_MIN
        )


class TestPrdStrengthFormula:
    def test_neutral_default_strength(self):
        # importance=0.5, emotion=0.5 → I=1.5, E=1.15
        expected = STRENGTH_BASE * 1.5 * 1.15 * 1.0 * 1.0
        assert compute_initial_strength(importance=0.5, emotion=0.5) == pytest.approx(
            expected
        )

    def test_high_importance_emotion_exceeds_default(self):
        neutral = compute_initial_strength(importance=0.5, emotion=0.5)
        strong = compute_initial_strength(importance=1.0, emotion=1.0)
        assert strong > neutral
        assert strong == pytest.approx(STRENGTH_BASE * 2.0 * 1.5 * 1.0 * 1.0)

    def test_prd_max_product(self):
        strength = compute_initial_strength(
            importance=1.0,
            emotion=1.0,
            encode_repetitions=0,
            successful_retrievals=7,
            consistency="consistent",
        )
        assert strength == pytest.approx(PRD_STRENGTH_MAX)


class TestRetentionScaling:
    def test_high_strength_decays_slower_than_prd_default(self):
        layer_ret = 0.5
        default_s = compute_initial_strength(importance=0.5, emotion=0.5)
        high_s = compute_initial_strength(importance=1.0, emotion=1.0)
        assert high_s > default_s
        assert apply_strength_to_retention(layer_ret, high_s) > apply_strength_to_retention(
            layer_ret, default_s
        )


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
            default_s = compute_initial_strength(importance=0.5, emotion=0.5)
            assert receipt.importance >= 0.5
            assert receipt.initial_strength > default_s
            assert "30d" in receipt.decay_estimate
        finally:
            mem.close()

    def test_routine_add_near_prd_default_strength(self, clock):
        mem = HMArch(
            config=MemoryConfig(db_path=":memory:"),
            time_provider=clock,
        )
        try:
            receipt = mem.add("Hello world")
            expected = compute_initial_strength(importance=0.5, emotion=0.5)
            assert receipt.initial_strength == pytest.approx(expected, abs=0.15)
        finally:
            mem.close()

    def test_encode_repetition_increases_initial_strength(self, clock):
        mem = HMArch(
            config=MemoryConfig(db_path=":memory:"),
            time_provider=clock,
        )
        try:
            first = mem.add("User prefers Python", importance=0.5)
            second = mem.add("User prefers Python", importance=0.5)
            assert second.initial_strength > first.initial_strength
        finally:
            mem.close()

    def test_search_reinforces_linked_l2_at_most_once(self, clock):
        mem = HMArch(
            config=MemoryConfig(
                db_path=":memory:",
                auto_consolidate=False,
                retrieval_relevance_threshold=0.1,
            ),
            time_provider=clock,
        )
        try:
            receipt = mem.add("User prefers Python")
            mem.search("User prefers Python", top_k=10)
            meta = json.loads(
                mem._db.query(
                    "SELECT metadata FROM memory_index WHERE id = ?",
                    (receipt.memory_id,),
                )[0]["metadata"]
            )
            block = meta["hm_arch_strength"]
            assert block["successful_retrievals"] == 1
        finally:
            mem.close()

    def test_high_strength_caps_current_retention_at_encode(self, clock):
        mem = HMArch(
            config=MemoryConfig(db_path=":memory:"),
            time_provider=clock,
        )
        try:
            receipt = mem.add(
                "CRITICAL production outage",
                event_type=EventType.ERROR,
                importance=1.0,
            )
            row = mem._db.query(
                """
                SELECT initial_strength, current_retention
                FROM memory_index WHERE id = ?
                """,
                (receipt.memory_id,),
            )[0]
            strength = float(row["initial_strength"])
            retention = float(row["current_retention"])
            assert strength > 1.0
            assert retention <= 1.0
            assert retention == pytest.approx(min(1.0, strength))
            assert float(row["initial_strength"]) == pytest.approx(
                receipt.initial_strength
            )
        finally:
            mem.close()

    def test_repeated_search_strengthens_default_memory(self, clock):
        mem = HMArch(
            config=MemoryConfig(
                db_path=":memory:",
                auto_consolidate=False,
                retrieval_relevance_threshold=0.1,
            ),
            time_provider=clock,
        )
        try:
            receipt = mem.add("User prefers Python")
            strengths = [receipt.initial_strength]
            for _ in range(3):
                mem.search("User prefers Python", top_k=1)
                row = mem._db.query(
                    "SELECT initial_strength FROM memory_index WHERE id = ?",
                    (receipt.memory_id,),
                )[0]
                strengths.append(float(row["initial_strength"]))
            assert strengths == sorted(strengths)
            assert strengths[-1] > strengths[0]
        finally:
            mem.close()

    def test_high_strength_retains_more_after_decay_than_default(self, clock):
        from hm_arch.consolidation import ConsolidationEngine

        mem = HMArch(
            config=MemoryConfig(db_path=":memory:", replay_sample_ratio=1.0),
            time_provider=clock,
        )
        try:
            default = mem.add("routine status update", importance=0.5)
            strong = mem.add(
                "CRITICAL production outage",
                event_type=EventType.ERROR,
                importance=1.0,
            )
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
            assert rows[strong.memory_id] > rows[default.memory_id]
        finally:
            mem.close()


class TestSemanticConsistencyStrength:
    def test_l3_encode_caps_current_retention(self):
        db = SQLiteStore(":memory:").connect()
        db.initialize_schema()
        cfg = MemoryConfig(db_path=":memory:", strength_max=10.0)
        l3 = L3SemanticMemory(db, config=cfg)
        mid = l3.upsert("user", "prefers", "Python", importance=1.0)
        row = db.query(
            """
            SELECT initial_strength, current_retention
            FROM memory_index WHERE id = ?
            """,
            (mid,),
        )[0]
        strength = float(row["initial_strength"])
        retention = float(row["current_retention"])
        assert strength > 1.0
        assert retention <= 1.0
        assert retention == pytest.approx(min(1.0, strength))
        db.close()

    def test_consistent_reupsert_boosts_strength(self):
        config = MemoryConfig(strength_max=10.0)
        db = SQLiteStore(":memory:").connect()
        db.initialize_schema()
        l3 = L3SemanticMemory(db, config=config)
        mid = l3.upsert("user", "prefers", "Python", importance=0.5)
        before = float(
            db.query(
                "SELECT initial_strength FROM memory_index WHERE id = ?", (mid,)
            )[0]["initial_strength"]
        )
        l3.upsert("user", "prefers", "Python", importance=0.5)
        after = float(
            db.query(
                "SELECT initial_strength FROM memory_index WHERE id = ?", (mid,)
            )[0]["initial_strength"]
        )
        assert after > before
        db.close()

    def test_conflict_superseded_penalizes_old_fact(self):
        clock = ManualTimeProvider()
        config = MemoryConfig(strength_max=10.0)
        db = SQLiteStore(":memory:").connect()
        db.initialize_schema()
        l3 = L3SemanticMemory(db, config=config, time_provider=clock)
        old_id = l3.upsert("user", "prefers", "Python", importance=0.5)
        old_strength = float(
            db.query(
                "SELECT initial_strength FROM memory_index WHERE id = ?",
                (old_id,),
            )[0]["initial_strength"]
        )
        l3.upsert("user", "prefers", "Rust", importance=0.5)
        superseded = float(
            db.query(
                "SELECT initial_strength FROM memory_index WHERE id = ?", (old_id,)
            )[0]["initial_strength"]
        )
        assert superseded < old_strength
        db.close()

    def test_l3_respects_custom_config_bounds(self):
        clock = ManualTimeProvider()
        config = MemoryConfig(strength_min=0.5, strength_max=0.9)
        db = SQLiteStore(":memory:").connect()
        db.initialize_schema()
        l3 = L3SemanticMemory(db, config=config, time_provider=clock)
        mid = l3.upsert("user", "prefers", "Python", importance=1.0)
        strength = float(
            db.query(
                "SELECT initial_strength FROM memory_index WHERE id = ?", (mid,)
            )[0]["initial_strength"]
        )
        assert strength == pytest.approx(0.9)
        clock.advance(hours=1)
        l3.upsert("user", "prefers", "Python", importance=1.0)
        updated = db.query(
            "SELECT updated_at FROM memory_index WHERE id = ?", (mid,)
        )[0]["updated_at"]
        assert updated.startswith("2024-01-01")
        db.close()


class TestRetrievalReinforcement:
    def test_apply_retrieval_reinforcement_increments_metadata(self):
        clock = ManualTimeProvider()
        config = MemoryConfig(db_path=":memory:")
        db = SQLiteStore(":memory:").connect()
        db.initialize_schema()
        factors = StrengthFactors(importance=0.5, emotion=0.5)
        strength = compute_initial_strength(
            importance=0.5, emotion=0.5, strength_max=config.strength_max
        )
        meta = json.dumps(
            {
                "hm_arch_strength": {
                    "importance": 0.5,
                    "emotion": 0.5,
                    "encode_repetitions": 0,
                    "successful_retrievals": 0,
                    "consistency": "neutral",
                }
            }
        )
        db.execute(
            """
            INSERT INTO memory_index (
                id, layer, created_at, updated_at, importance,
                initial_strength, current_retention, status,
                tags, metadata, content_hash
            ) VALUES (?, 2, ?, ?, ?, ?, ?, 'active', '[]', ?, ?)
            """,
            (
                "m1",
                clock.now().isoformat(),
                clock.now().isoformat(),
                0.5,
                strength,
                strength,
                meta,
                "hash",
            ),
        )
        db.execute(
            """
            INSERT INTO episodes (
                id, memory_id, content, event_type, emotion_score
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("e1", "m1", "text", "conversation", 0.5),
        )
        assert apply_retrieval_reinforcement(
            db, "m1", 0.9, config=config, time_provider=clock
        )
        row = db.query(
            "SELECT initial_strength, metadata FROM memory_index WHERE id = ?",
            ("m1",),
        )[0]
        block = json.loads(row["metadata"])["hm_arch_strength"]
        assert block["successful_retrievals"] == 1
        assert float(row["initial_strength"]) > strength
        db.close()


class TestConfigAndExports:
    def test_memory_config_strength_fields(self):
        cfg = MemoryConfigCls()
        assert cfg.strength_min == pytest.approx(0.2)
        assert cfg.strength_max == pytest.approx(6.75)
        assert cfg.retrieval_reinforcement_increment == pytest.approx(0.3)

    def test_forgetting_package_exports_strength_helpers(self):
        import hm_arch.forgetting as forgetting

        assert forgetting.STRENGTH_BASE == pytest.approx(0.5)
        assert forgetting.compute_initial_strength is not None
        assert forgetting.apply_retrieval_reinforcement is not None
