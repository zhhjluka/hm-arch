"""Tests for the consolidation engine (HM-10).

Acceptance criteria:
* Clear preference text creates a semantic triple in L3.
* ``run_consolidation_cycle()`` returns a ``ConsolidationReport``.
* The review queue is populated for important low-retention memories.

All tests are offline (no LLM / API key required).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hm_arch.config import MemoryConfig
from hm_arch.consolidation import ConsolidationEngine, SemanticExtractor
from hm_arch.consolidation.replay import _l2_retention, _l3_retention
from hm_arch import HMArch
from hm_arch.layers.l2_episodic import L2EpisodicBuffer
from hm_arch.layers.l3_semantic import L3SemanticMemory
from hm_arch.layers.l4_ltm import L4EpisodicLTM
from hm_arch.storage.sqlite import SQLiteStore
from hm_arch.types import ConsolidationReport, EventType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    """In-memory SQLite store with the full schema initialised."""
    store = SQLiteStore(":memory:").connect()
    store.initialize_schema()
    yield store
    store.close()


@pytest.fixture()
def l2(db):
    return L2EpisodicBuffer(db)


@pytest.fixture()
def l3(db):
    return L3SemanticMemory(db)


@pytest.fixture()
def config_full_sample():
    """Config that samples all episodes so tests are deterministic."""
    return MemoryConfig(replay_sample_ratio=1.0)


@pytest.fixture()
def engine(db, l2, l3, config_full_sample):
    return ConsolidationEngine(db, l2, l3, config=config_full_sample)


@pytest.fixture()
def l4(tmp_path: Path):
    return L4EpisodicLTM(tmp_path)


@pytest.fixture()
def engine_with_l4(db, l2, l3, l4, config_full_sample):
    return ConsolidationEngine(db, l2, l3, l4=l4, config=config_full_sample)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_old_created_at(db: SQLiteStore, memory_id: str, days_ago: int) -> None:
    """Back-date ``created_at`` for *memory_id* to simulate an old memory."""
    old_time = (datetime.now(tz=timezone.utc) - timedelta(days=days_ago)).isoformat()
    db.execute(
        "UPDATE memory_index SET created_at = ? WHERE id = ?",
        (old_time, memory_id),
    )


# ===========================================================================
# SemanticExtractor tests
# ===========================================================================


class TestSemanticExtractor:
    """Unit tests for the fallback semantic extractor."""

    def setup_method(self):
        self.ex = SemanticExtractor()

    # --- Empty / trivial input ---

    def test_empty_string_returns_empty(self):
        assert self.ex.extract("") == []

    def test_whitespace_only_returns_empty(self):
        assert self.ex.extract("   ") == []

    def test_gibberish_returns_empty(self):
        assert self.ex.extract("xyzzy frobble wumpus") == []

    # --- Acceptance: clear preference text → semantic triple ---

    def test_user_prefers_python(self):
        triples = self.ex.extract("User prefers Python")
        assert len(triples) == 1
        assert triples[0] == ("user", "prefers", "Python")

    def test_user_likes_javascript(self):
        triples = self.ex.extract("User likes JavaScript")
        assert len(triples) == 1
        assert triples[0] == ("user", "likes", "JavaScript")

    def test_user_hates_java(self):
        triples = self.ex.extract("User hates Java")
        assert len(triples) == 1
        assert triples[0] == ("user", "hates", "Java")

    def test_user_uses_typescript(self):
        triples = self.ex.extract("User uses TypeScript")
        assert len(triples) == 1
        assert triples[0] == ("user", "uses", "TypeScript")

    # --- First-person subject normalisation ---

    def test_first_person_i_like(self):
        triples = self.ex.extract("I like Python")
        assert len(triples) == 1
        entity, relation, value = triples[0]
        assert entity == "user"
        assert relation == "likes"
        assert value == "Python"

    def test_first_person_i_prefer(self):
        triples = self.ex.extract("I prefer Python")
        assert len(triples) == 1
        assert triples[0] == ("user", "prefers", "Python")

    def test_the_user_alias(self):
        triples = self.ex.extract("The user prefers Go")
        assert len(triples) == 1
        assert triples[0][0] == "user"

    def test_me_alias(self):
        triples = self.ex.extract("Me wants coffee")
        assert len(triples) == 1
        assert triples[0][0] == "user"

    # --- Verb canonicalisation ---

    def test_verb_prefer_canonicalised(self):
        triples = self.ex.extract("I prefer Rust")
        assert triples[0][1] == "prefers"

    def test_verb_like_canonicalised(self):
        triples = self.ex.extract("I like Rust")
        assert triples[0][1] == "likes"

    def test_verb_avoid_canonicalised(self):
        triples = self.ex.extract("User avoids PHP")
        assert triples[0][1] == "avoids"

    def test_verb_dislike_canonicalised(self):
        triples = self.ex.extract("User dislikes PHP")
        assert triples[0][1] == "dislikes"

    # --- Period stripping ---

    def test_trailing_period_stripped_from_value(self):
        triples = self.ex.extract("User prefers Python.")
        assert len(triples) == 1
        assert triples[0][2] == "Python"

    # --- CJK support ---

    def test_cjk_pian_hao(self):
        """用户偏好 Python → ('user', 'prefers', 'Python')"""
        triples = self.ex.extract("用户偏好 Python")
        assert len(triples) == 1
        assert triples[0] == ("user", "prefers", "Python")

    def test_cjk_xi_huan(self):
        """用户喜欢 Rust → ('user', 'likes', 'Rust')"""
        triples = self.ex.extract("用户喜欢 Rust")
        assert len(triples) == 1
        assert triples[0] == ("user", "likes", "Rust")

    # --- Copula "is" pattern ---

    def test_is_pattern_basic(self):
        triples = self.ex.extract("Python is a programming language")
        assert len(triples) == 1
        entity, relation, value = triples[0]
        assert relation == "is"
        assert "programming language" in value

    # --- Possession "has" pattern ---

    def test_has_pattern_basic(self):
        triples = self.ex.extract("The project has a README")
        assert len(triples) == 1
        assert triples[0][1] == "has"

    # --- Non-user subjects are preserved ---

    def test_non_user_subject_preserved(self):
        triples = self.ex.extract("Python likes simplicity")
        assert len(triples) == 1
        entity = triples[0][0]
        assert entity == "python"


# ===========================================================================
# Retention decay formula tests
# ===========================================================================


class TestRetentionFormulas:
    """Validate that L2 / L3 decay formulas match PRD reference values."""

    def test_l2_retention_at_zero_hours(self):
        cfg = MemoryConfig()
        assert _l2_retention(0.0, cfg) == pytest.approx(1.0, abs=1e-9)

    def test_l2_retention_at_30_days(self):
        """PRD states L2 retention ≈ 0.26 at 30 days."""
        cfg = MemoryConfig()
        ret = _l2_retention(30 * 24, cfg)
        assert 0.20 < ret < 0.35

    def test_l3_retention_at_zero_hours(self):
        cfg = MemoryConfig()
        assert _l3_retention(0.0, cfg) == pytest.approx(1.0, abs=1e-9)

    def test_l3_retention_at_30_days(self):
        """PRD states L3 retention ≈ 0.63 at 30 days."""
        cfg = MemoryConfig()
        ret = _l3_retention(30 * 24, cfg)
        assert 0.55 < ret < 0.75

    def test_l2_decays_faster_than_l3(self):
        cfg = MemoryConfig()
        t = 7 * 24  # 7 days
        assert _l2_retention(t, cfg) < _l3_retention(t, cfg)


# ===========================================================================
# ConsolidationEngine — basic contract tests
# ===========================================================================


class TestConsolidationEngineContract:
    """Basic contract: report shape, log written, empty store is safe."""

    def test_returns_consolidation_report(self, engine):
        """run_consolidation_cycle() returns a ConsolidationReport instance."""
        report = engine.run_consolidation_cycle()
        assert isinstance(report, ConsolidationReport)

    def test_report_has_non_negative_duration(self, engine):
        report = engine.run_consolidation_cycle()
        assert report.duration_seconds >= 0

    def test_report_fields_are_non_negative(self, engine):
        report = engine.run_consolidation_cycle()
        assert report.extracted_semantics >= 0
        assert report.merged_duplicates >= 0
        assert report.resolved_conflicts >= 0
        assert report.archived_to_l4 >= 0
        assert report.scheduled_reviews >= 0
        assert report.marked_deletable >= 0

    def test_empty_memory_store_runs_without_error(self, engine):
        report = engine.run_consolidation_cycle()
        assert report.extracted_semantics == 0
        assert report.scheduled_reviews == 0
        assert report.marked_deletable == 0

    def test_consolidation_log_row_written(self, engine, db):
        engine.run_consolidation_cycle()
        rows = db.query("SELECT * FROM consolidation_log")
        assert len(rows) == 1

    def test_consolidation_log_stats_json_valid(self, engine, db):
        engine.run_consolidation_cycle()
        rows = db.query("SELECT stats FROM consolidation_log")
        stats = json.loads(rows[0]["stats"])
        expected_keys = {
            "extracted_semantics",
            "merged_duplicates",
            "resolved_conflicts",
            "archived_to_l4",
            "scheduled_reviews",
            "marked_deletable",
        }
        assert expected_keys.issubset(stats.keys())

    def test_multiple_cycles_append_log_rows(self, engine, db):
        engine.run_consolidation_cycle()
        engine.run_consolidation_cycle()
        rows = db.query("SELECT * FROM consolidation_log")
        assert len(rows) == 2


# ===========================================================================
# Acceptance: preference text → semantic triple
# ===========================================================================


class TestSemanticExtractionAcceptance:
    """Acceptance test: clear preference text creates a semantic triple in L3."""

    def test_preference_episode_creates_l3_triple(self, db, l2, l3, engine):
        l2.encode(
            "User prefers Python",
            event_type=EventType.CONVERSATION,
            importance=0.8,
        )
        report = engine.run_consolidation_cycle()

        assert report.extracted_semantics == 1

        fact = l3.get_by_entity_relation("user", "prefers")
        assert fact is not None
        assert fact.entity == "user"
        assert fact.relation == "prefers"
        assert fact.value == "Python"

    def test_first_person_preference_creates_triple(self, db, l2, l3, engine):
        l2.encode("I like Rust", event_type=EventType.CONVERSATION, importance=0.7)
        engine.run_consolidation_cycle()

        fact = l3.get_by_entity_relation("user", "likes")
        assert fact is not None
        assert fact.value == "Rust"

    def test_cjk_preference_creates_triple(self, db, l2, l3, engine):
        """Acceptance: 用户偏好 Python → L3 triple."""
        l2.encode(
            "用户偏好 Python",
            event_type=EventType.CONVERSATION,
            importance=0.8,
        )
        report = engine.run_consolidation_cycle()

        assert report.extracted_semantics >= 1

        fact = l3.get_by_entity_relation("user", "prefers")
        assert fact is not None
        assert fact.value == "Python"

    def test_source_episode_linked_to_triple(self, db, l2, l3, engine):
        mid = l2.encode("User prefers Go", importance=0.8)
        engine.run_consolidation_cycle()

        fact = l3.get_by_entity_relation("user", "prefers")
        assert fact is not None
        assert mid in fact.source_episodes

    def test_non_preference_episode_produces_no_triple(self, db, l2, l3, engine):
        l2.encode(
            "Fixed the off-by-one error in loop counter",
            event_type=EventType.CODE,
            importance=0.6,
        )
        report = engine.run_consolidation_cycle()
        assert report.extracted_semantics == 0

    def test_multiple_preference_episodes_each_create_triple(self, db, l2, l3, engine):
        l2.encode("User prefers Python", importance=0.8)
        l2.encode("User uses Docker", importance=0.7)
        report = engine.run_consolidation_cycle()
        # Both episodes match — expect at least 2 extracted triples.
        assert report.extracted_semantics >= 2

        lang_fact = l3.get_by_entity_relation("user", "prefers")
        tool_fact = l3.get_by_entity_relation("user", "uses")
        assert lang_fact is not None
        assert tool_fact is not None


# ===========================================================================
# Conflict resolution
# ===========================================================================


class TestConflictResolution:
    """Verify that contradictory preferences are tracked as resolved conflicts."""

    def test_conflicting_preference_counted(self, db, l2, l3, config_full_sample):
        engine = ConsolidationEngine(db, l2, l3, config=config_full_sample)

        l2.encode("User prefers Python", importance=0.8)
        engine.run_consolidation_cycle()

        l2.encode("User prefers Java", importance=0.8)
        report2 = engine.run_consolidation_cycle()

        assert report2.resolved_conflicts >= 1

    def test_superseded_old_fact(self, db, l2, l3, config_full_sample):
        engine = ConsolidationEngine(db, l2, l3, config=config_full_sample)

        l2.encode("User prefers Python", importance=0.8)
        engine.run_consolidation_cycle()

        # Confirm Python fact exists.
        assert l3.get_by_entity_relation("user", "prefers") is not None

        # Now consolidate a conflicting preference.
        l2.encode("User prefers Java", importance=0.9)
        engine.run_consolidation_cycle()

        # The active fact should be whatever was last upserted.
        active_fact = l3.get_by_entity_relation("user", "prefers")
        assert active_fact is not None
        # One value superseded the other — superseded count in L3 should be ≥ 1.
        assert l3.count(status="superseded") >= 1

    def test_idempotent_same_preference_no_conflict(self, db, l2, l3, config_full_sample):
        """Upserting the same (entity, relation, value) is idempotent."""
        engine = ConsolidationEngine(db, l2, l3, config=config_full_sample)

        l2.encode("User prefers Python", importance=0.8)
        report1 = engine.run_consolidation_cycle()

        l2.encode("User prefers Python", importance=0.8)
        report2 = engine.run_consolidation_cycle()

        assert report2.resolved_conflicts == 0


# ===========================================================================
# Retention field updates
# ===========================================================================


class TestRetentionUpdates:
    """Verify that consolidation writes updated retention to memory_index."""

    def test_retention_decays_for_old_l2_memory(self, db, l2, engine):
        mid = l2.encode("Some event", importance=0.5)
        _set_old_created_at(db, mid, days_ago=15)  # expect ~0.42

        engine.run_consolidation_cycle()

        rows = db.query(
            "SELECT current_retention FROM memory_index WHERE id = ?", (mid,)
        )
        assert len(rows) == 1
        ret = rows[0]["current_retention"]
        assert ret < 1.0, "Retention should have decayed below 1.0"
        assert ret > 0.0

    def test_retention_decays_for_old_l3_memory(self, db, l3, engine):
        mid = l3.upsert("project", "uses", "SQLite")
        _set_old_created_at(db, mid, days_ago=60)

        engine.run_consolidation_cycle()

        rows = db.query(
            "SELECT current_retention FROM memory_index WHERE id = ?", (mid,)
        )
        ret = rows[0]["current_retention"]
        assert ret < 1.0
        assert ret > 0.0

    def test_fresh_memory_retention_near_one(self, db, l2, engine):
        """A memory created seconds ago should still have retention ≈ 1.0."""
        mid = l2.encode("Just happened", importance=0.5)
        engine.run_consolidation_cycle()

        rows = db.query(
            "SELECT current_retention FROM memory_index WHERE id = ?", (mid,)
        )
        ret = rows[0]["current_retention"]
        assert ret > 0.99


# ===========================================================================
# Acceptance: review queue populated for important stale memories
# ===========================================================================


class TestReviewQueueAcceptance:
    """Acceptance test: review queue is populated for important stale memories."""

    def test_important_stale_memory_scheduled_for_review(self, db, l2, engine):
        mid = l2.encode("User prefers Python", importance=0.8)
        # Back-date so retention decays to ≈ 0.42 (below 0.5 trigger).
        _set_old_created_at(db, mid, days_ago=15)

        report = engine.run_consolidation_cycle()

        assert report.scheduled_reviews >= 1

        rows = db.query(
            "SELECT * FROM review_queue WHERE memory_id = ?", (mid,)
        )
        assert len(rows) == 1
        assert rows[0]["ef"] == pytest.approx(2.5)
        assert rows[0]["current_interval"] == 1

    def test_low_importance_memory_not_scheduled(self, db, l2, engine):
        """Memories with importance < 0.5 should not enter the review queue."""
        mid = l2.encode("Minor observation", importance=0.3)
        _set_old_created_at(db, mid, days_ago=15)

        report = engine.run_consolidation_cycle()

        rows = db.query(
            "SELECT * FROM review_queue WHERE memory_id = ?", (mid,)
        )
        assert len(rows) == 0

    def test_high_retention_memory_not_scheduled(self, db, l2, engine):
        """Fresh memories (retention ≈ 1.0) should not enter the review queue."""
        mid = l2.encode("Recent event", importance=0.9)
        # No back-dating — retention stays near 1.0.

        report = engine.run_consolidation_cycle()

        rows = db.query(
            "SELECT * FROM review_queue WHERE memory_id = ?", (mid,)
        )
        assert len(rows) == 0

    def test_memory_not_duplicated_in_review_queue(self, db, l2, engine):
        """Running two cycles must not insert duplicate review_queue rows."""
        mid = l2.encode("User prefers Python", importance=0.8)
        _set_old_created_at(db, mid, days_ago=15)

        engine.run_consolidation_cycle()
        engine.run_consolidation_cycle()

        rows = db.query(
            "SELECT * FROM review_queue WHERE memory_id = ?", (mid,)
        )
        assert len(rows) == 1, "memory must appear at most once in review_queue"

    def test_urgency_higher_for_important_stale_memory(self, db, l2, engine):
        """Higher importance + lower retention → higher urgency score."""
        mid_high = l2.encode("Critical preference", importance=0.9)
        mid_low = l2.encode("Minor preference", importance=0.51)
        _set_old_created_at(db, mid_high, days_ago=15)
        _set_old_created_at(db, mid_low, days_ago=15)

        engine.run_consolidation_cycle()

        rows = db.query(
            "SELECT memory_id, urgency FROM review_queue ORDER BY urgency DESC"
        )
        memory_ids_by_urgency = [r["memory_id"] for r in rows]
        # The high-importance memory should have higher urgency.
        assert memory_ids_by_urgency[0] == mid_high


# ===========================================================================
# Mark-deletable
# ===========================================================================


class TestMarkDeletable:
    """Verify that very-low-retention memories are flagged as 'deletable'."""

    def test_very_old_l2_memory_marked_deletable(self, db, l2, engine):
        """L2 retention at 90 days ≈ 0.025, below the 0.05 delete threshold."""
        mid = l2.encode("Ancient event", importance=0.5)
        _set_old_created_at(db, mid, days_ago=90)

        report = engine.run_consolidation_cycle()

        assert report.marked_deletable >= 1

        rows = db.query(
            "SELECT status FROM memory_index WHERE id = ?", (mid,)
        )
        assert rows[0]["status"] == "deletable"

    def test_moderate_l2_memory_not_marked_deletable(self, db, l2, engine):
        """L2 retention at 15 days ≈ 0.42, above the 0.05 delete threshold."""
        mid = l2.encode("Moderately old event", importance=0.5)
        _set_old_created_at(db, mid, days_ago=15)

        report = engine.run_consolidation_cycle()

        rows = db.query(
            "SELECT status FROM memory_index WHERE id = ?", (mid,)
        )
        assert rows[0]["status"] == "active"

    def test_deletable_memories_not_in_l2_sample(self, db, l2, l3, engine):
        """Memories already marked deletable by a previous cycle are excluded from replay."""
        mid = l2.encode("Old preference mention", importance=0.5)
        _set_old_created_at(db, mid, days_ago=90)

        # First cycle marks it deletable.
        engine.run_consolidation_cycle()

        rows = db.query(
            "SELECT status FROM memory_index WHERE id = ?", (mid,)
        )
        assert rows[0]["status"] == "deletable"

        # Second cycle should not see it in the active L2 pool.
        report2 = engine.run_consolidation_cycle()
        # No new triples from a deleted memory.
        assert report2.extracted_semantics == 0


# ===========================================================================
# L4 archive integration (HM-19)
# ===========================================================================


class TestL4ArchiveIntegration:
    """Verify consolidation archives low-retention L2 episodes to L4."""

    def test_archives_l2_below_threshold(self, db, l2, engine_with_l4, l4):
        mid = l2.encode("Ancient preference detail", importance=0.6)
        _set_old_created_at(db, mid, days_ago=60)

        report = engine_with_l4.run_consolidation_cycle()

        assert report.archived_to_l4 >= 1
        assert l4.retrieve(mid) is not None

        rows = db.query(
            "SELECT layer, status, metadata FROM memory_index WHERE id = ?",
            (mid,),
        )
        assert rows[0]["layer"] == 4
        assert rows[0]["status"] == "archived"
        meta = json.loads(rows[0]["metadata"])
        assert meta["source_l2_memory_id"] == mid

    def test_archived_memory_not_in_active_l2_count(self, db, l2, engine_with_l4):
        mid = l2.encode("Stale episodic note", importance=0.5)
        _set_old_created_at(db, mid, days_ago=60)
        assert l2.count() == 1

        engine_with_l4.run_consolidation_cycle()

        assert l2.count() == 0

    def test_moderate_retention_not_archived(self, db, l2, engine_with_l4, l4):
        mid = l2.encode("Moderately old event", importance=0.5)
        _set_old_created_at(db, mid, days_ago=15)

        report = engine_with_l4.run_consolidation_cycle()

        assert report.archived_to_l4 == 0
        assert l4.retrieve(mid) is None
        rows = db.query("SELECT status FROM memory_index WHERE id = ?", (mid,))
        assert rows[0]["status"] == "active"


# ===========================================================================
# Weighted L2 replay sampling
# ===========================================================================


class TestWeightedL2Replay:
    """Verify deterministic importance × decay weighted replay sampling."""

    def test_important_stale_episode_replayed_before_fresh_minor(self, db, l2, l3):
        config = MemoryConfig(replay_sample_ratio=0.5)
        engine = ConsolidationEngine(db, l2, l3, config=config)

        stale_id = l2.encode("User prefers Python", importance=0.9)
        fresh_id = l2.encode("User uses Docker", importance=0.3)
        _set_old_created_at(db, stale_id, days_ago=15)

        report = engine.run_consolidation_cycle()

        assert report.extracted_semantics == 1
        assert l3.get_by_entity_relation("user", "prefers") is not None
        assert l3.get_by_entity_relation("user", "uses") is None

    def test_weighted_sampling_is_deterministic(self, db, l2, l3):
        config = MemoryConfig(replay_sample_ratio=0.5)
        engine = ConsolidationEngine(db, l2, l3, config=config)

        stale_id = l2.encode("User prefers Python", importance=0.9)
        l2.encode("User uses Docker", importance=0.3)
        _set_old_created_at(db, stale_id, days_ago=15)

        first = engine._sample_l2_episodes()
        second = engine._sample_l2_episodes()
        assert [ep["memory_id"] for ep in first] == [ep["memory_id"] for ep in second]


# ===========================================================================
# Redundant semantic merge
# ===========================================================================


class TestRedundantSemanticMerge:
    """Verify near-duplicate semantic facts merge instead of duplicating."""

    def test_near_duplicate_values_merge(self, db, l2, l3, engine):
        canonical = "alpha beta gamma delta epsilon zeta"
        near_dup = "alpha beta gamma delta epsilon zeta eta"

        l3.upsert("user", "prefers", canonical, source_episodes=["seed"])
        l2.encode(f"User prefers {near_dup}", importance=0.8)

        report = engine.run_consolidation_cycle()

        assert report.merged_duplicates >= 1
        assert l3.count(status="active") == 1
        fact = l3.get_by_entity_relation("user", "prefers")
        assert fact is not None
        assert "seed" in fact.source_episodes

    def test_conflicting_values_still_supersede(self, db, l2, l3, config_full_sample):
        engine = ConsolidationEngine(db, l2, l3, config=config_full_sample)

        l2.encode("User prefers Python", importance=0.8)
        engine.run_consolidation_cycle()

        l2.encode("User prefers Java", importance=0.9)
        report = engine.run_consolidation_cycle()

        assert report.resolved_conflicts >= 1
        assert l3.count(status="superseded") >= 1
        active = l3.get_by_entity_relation("user", "prefers")
        assert active is not None
        assert active.value == "Java"


# ===========================================================================
# 7-day simulated agent scenario
# ===========================================================================


class TestSevenDayAgentSimulation:
    """End-to-end offline simulation of a week-long coding-agent memory loop."""

    def test_seven_day_sleep_cycle(self, tmp_path: Path):
        archive_root = tmp_path / "archives"
        db_path = tmp_path / "agent.db"
        config = MemoryConfig(
            replay_sample_ratio=1.0,
            archive_root=str(archive_root),
            db_path=str(db_path),
        )
        memory = HMArch(config=config)

        preference_ids: list[str] = []
        code_ids: list[str] = []

        for day in range(7):
            pref_id = memory.add(
                "User prefers Python",
                event_type=EventType.CONVERSATION,
                importance=0.85,
            ).memory_id
            code_id = memory.add(
                f"Fixed regression in module day-{day}",
                event_type=EventType.CODE,
                importance=0.55,
            ).memory_id
            preference_ids.append(pref_id)
            code_ids.append(code_id)

            _set_old_created_at(memory._db, pref_id, days_ago=15 + day)
            _set_old_created_at(memory._db, code_id, days_ago=60 + day)

            report = memory.consolidate()
            assert isinstance(report, ConsolidationReport)
            assert report.duration_seconds >= 0

        final_stats = memory.get_stats()
        assert final_stats.by_layer[3] >= 1
        assert final_stats.review_queue_length >= 1

        rows = memory._db.query("SELECT COUNT(*) AS n FROM consolidation_log")
        assert rows[0]["n"] == 7

        pref_fact = memory._l3.get_by_entity_relation("user", "prefers")
        assert pref_fact is not None
        assert pref_fact.value == "Python"

        search = memory.search("user prefers Python", top_k=10)
        assert search.source_breakdown.get(3, 0) >= 1

        archived_rows = memory._db.query(
            "SELECT COUNT(*) AS n FROM memory_index WHERE layer = 4 AND status = 'archived'"
        )
        assert archived_rows[0]["n"] >= 1

        memory.close()


# ===========================================================================
# Custom extractor injection
# ===========================================================================


class TestCustomExtractor:
    """Verify that a custom extractor can be injected."""

    def test_custom_extractor_used(self, db, l2, l3, config_full_sample):
        class AlwaysExtracts(SemanticExtractor):
            def extract(self, content):
                return [("agent", "likes", "testing")]

        custom = AlwaysExtracts()
        engine = ConsolidationEngine(
            db, l2, l3, config=config_full_sample, extractor=custom
        )

        l2.encode("Anything at all", importance=0.7)
        report = engine.run_consolidation_cycle()

        assert report.extracted_semantics == 1
        fact = l3.get_by_entity_relation("agent", "likes")
        assert fact is not None
        assert fact.value == "testing"


# ===========================================================================
# Public import surface
# ===========================================================================


def test_consolidation_importable_from_package():
    """ConsolidationEngine and SemanticExtractor are importable from the package."""
    from hm_arch.consolidation import ConsolidationEngine as CE
    from hm_arch.consolidation import SemanticExtractor as SE

    assert CE is ConsolidationEngine
    assert SE is SemanticExtractor
