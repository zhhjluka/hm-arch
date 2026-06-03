"""End-to-end 30-day offline simulation for coding-agent memory (HM-24 / MEM-24).

Simulates nightly consolidation over 30 synthetic days using back-dated
``created_at`` timestamps (no sleeps, no wall-clock dependence). Validates:

* L2 / L3 retention at 30 days (≈ 0.26 / ≈ 0.63 per PRD)
* Preference supersession and search ranking for the latest semantic fact
* L4 archive growth for eligible stale episodic memories
* Review queue population for important low-retention memories

Suggested commands::

    uv run pytest tests/test_simulation_30_day.py
    uv run pytest tests/prd_benchmarks -m benchmark -v   # PRD scale (slow; see docs/benchmarks.md)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hm_arch import HMArch
from hm_arch.config import MemoryConfig
from hm_arch.consolidation.replay import _l2_retention, _l3_retention
from hm_arch.types import ConsolidationReport, EventType

HOURS_PER_DAY = 24
THIRTY_DAYS_HOURS = 30 * HOURS_PER_DAY


def _set_old_created_at(db, memory_id: str, *, days_ago: int) -> None:
    """Back-date ``created_at`` for *memory_id* to simulate age."""
    old_time = (datetime.now(tz=timezone.utc) - timedelta(days=days_ago)).isoformat()
    db.execute(
        "UPDATE memory_index SET created_at = ? WHERE id = ?",
        (old_time, memory_id),
    )


def _read_retention(db, memory_id: str) -> float:
    rows = db.query(
        "SELECT current_retention FROM memory_index WHERE id = ?",
        (memory_id,),
    )
    assert len(rows) == 1
    return float(rows[0]["current_retention"])


class TestThirtyDayRetentionCurves:
    """PRD reference retention at 30 days (theoretical decay, no simulation loop)."""

    def test_l2_retention_at_30_days(self) -> None:
        cfg = MemoryConfig()
        ret = _l2_retention(THIRTY_DAYS_HOURS, cfg)
        assert ret == pytest.approx(0.26, abs=0.05)

    def test_l3_retention_at_30_days(self) -> None:
        cfg = MemoryConfig()
        ret = _l3_retention(THIRTY_DAYS_HOURS, cfg)
        assert ret == pytest.approx(0.63, abs=0.05)

    def test_hmarch_retention_curve_matches_prd(self, tmp_path: Path) -> None:
        cfg = MemoryConfig(
            db_path=str(tmp_path / "curve.db"),
            archive_root=str(tmp_path / "archives"),
        )
        memory = HMArch(config=cfg)
        try:
            l2_curve = memory.get_retention_curve(layer=2, days=[30])
            l3_curve = memory.get_retention_curve(layer=3, days=[30])
            assert l2_curve.retention[0] == pytest.approx(0.26, abs=0.05)
            assert l3_curve.retention[0] == pytest.approx(0.63, abs=0.05)
        finally:
            memory.close()


class TestThirtyDayCodingAgentSimulation:
    """Simulate 30 days of agent memory events and verify long-run behavior."""

    def test_thirty_day_sleep_cycle(self, tmp_path: Path) -> None:
        archive_root = tmp_path / "archives"
        db_path = tmp_path / "agent.db"
        config = MemoryConfig(
            replay_sample_ratio=1.0,
            archive_root=str(archive_root),
            db_path=str(db_path),
        )
        memory = HMArch(config=config)

        preference_episode_ids: list[str] = []
        code_episode_ids: list[str] = []
        total_archived = 0

        try:
            preference_switch_day = 15
            for day in range(30):
                pref_id: str | None = None
                if day < preference_switch_day:
                    pref_id = memory.add(
                        "User prefers Python",
                        event_type=EventType.CONVERSATION,
                        importance=0.85,
                    ).memory_id
                    preference_episode_ids.append(pref_id)
                    _set_old_created_at(
                        memory._db, pref_id, days_ago=15 + day
                    )
                elif day == preference_switch_day:
                    # Fresh timestamp on switch day: stale-replay guard compares
                    # episode ``created_at`` to L3 ``created_at`` wall-clock time.
                    pref_id = memory.add(
                        "User prefers TypeScript",
                        event_type=EventType.CONVERSATION,
                        importance=0.9,
                    ).memory_id
                    preference_episode_ids.append(pref_id)

                code_id = memory.add(
                    f"Refactored auth module on simulated day {day}",
                    event_type=EventType.CODE,
                    importance=0.55,
                ).memory_id
                code_episode_ids.append(code_id)
                _set_old_created_at(memory._db, code_id, days_ago=45 + day)

                report = memory.consolidate()
                assert isinstance(report, ConsolidationReport)
                assert report.duration_seconds >= 0
                total_archived += report.archived_to_l4

            # --- Retention: stored rows after final decay pass ----------------
            l2_probe = memory.add(
                "L2 retention probe episode",
                event_type=EventType.CODE,
                importance=0.5,
            ).memory_id
            _set_old_created_at(memory._db, l2_probe, days_ago=30)
            memory.consolidate()
            l2_stored = _read_retention(memory._db, l2_probe)
            assert l2_stored == pytest.approx(0.26, abs=0.08)

            pref_fact = memory._l3.get_by_entity_relation("user", "prefers")
            assert pref_fact is not None

            # --- Preference supersession ------------------------------------
            assert pref_fact.value == "TypeScript"
            assert memory._l3.count(status="superseded") >= 1

            search = memory.search("user prefers TypeScript", top_k=10)
            l3_hits = [item for item in search.results if item.layer == 3]
            assert l3_hits, "L3 semantic memory should appear in search results"
            assert l3_hits[0].memory_id == pref_fact.memory_id
            assert "typescript" in l3_hits[0].content.lower()

            pref_fact = memory._l3.get_by_entity_relation("user", "prefers")
            assert pref_fact is not None and pref_fact.value == "TypeScript"
            _set_old_created_at(memory._db, pref_fact.memory_id, days_ago=30)
            # Decay-only: search may have triggered auto-consolidate replay.
            from hm_arch.consolidation import ConsolidationEngine

            memory._config.auto_consolidate = False
            ConsolidationEngine(
                memory._db,
                memory._l2,
                memory._l3,
                config=memory._config,
            )._update_retention_all()
            l3_stored = _read_retention(memory._db, pref_fact.memory_id)
            from hm_arch.forgetting.decay import l3_retention_from_config
            from hm_arch.forgetting.strength import apply_strength_to_retention

            strength_row = memory._db.query(
                "SELECT initial_strength FROM memory_index WHERE id = ?",
                (pref_fact.memory_id,),
            )[0]
            layer_30d = l3_retention_from_config(30 * 24, config)
            expected_l3 = apply_strength_to_retention(
                layer_30d, float(strength_row["initial_strength"])
            )
            assert l3_stored == pytest.approx(expected_l3, abs=0.08)

            # --- L4 archive growth ------------------------------------------
            assert total_archived >= 1
            archived_rows = memory._db.query(
                """
                SELECT COUNT(*) AS n
                FROM memory_index
                WHERE layer = 4 AND status = 'archived'
                """
            )
            assert archived_rows[0]["n"] >= 1
            assert memory._l4.list_archives(), "L4 filesystem should list archives"

            sample_archived_id = code_episode_ids[0]
            archived_meta = memory._db.query(
                "SELECT layer, status, metadata FROM memory_index WHERE id = ?",
                (sample_archived_id,),
            )
            if archived_meta and archived_meta[0]["layer"] == 4:
                meta = json.loads(archived_meta[0]["metadata"])
                assert meta.get("source_l2_memory_id") == sample_archived_id
                assert memory._l4.retrieve(sample_archived_id) is not None

            # --- Review queue -----------------------------------------------
            stats = memory.get_stats()
            assert stats.review_queue_length >= 1

            review_rows = memory._db.query(
                """
                SELECT rq.memory_id, rq.urgency, mi.importance, mi.current_retention
                FROM review_queue rq
                JOIN memory_index mi ON mi.id = rq.memory_id
                ORDER BY rq.urgency DESC
                """
            )
            assert review_rows
            top_review = review_rows[0]
            assert float(top_review["importance"]) >= 0.5
            assert float(top_review["current_retention"]) < config.review_trigger_retention

            # Important preference episodes should be represented in the queue.
            queued_ids = {row["memory_id"] for row in review_rows}
            assert queued_ids.intersection(set(preference_episode_ids))

            # --- Consolidation audit trail ------------------------------------
            log_rows = memory._db.query("SELECT COUNT(*) AS n FROM consolidation_log")
            # 30 daily consolidations + L2 probe; search may add an auto tick.
            assert log_rows[0]["n"] >= 30

            assert memory._l3.count(status="active") >= 1
            assert stats.by_layer[3] >= 1
        finally:
            memory.close()
