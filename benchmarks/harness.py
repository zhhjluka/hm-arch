"""Reproducible PRD benchmark harness (offline, deterministic)."""

from __future__ import annotations

import json
import platform
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from hm_arch import HMArch
from hm_arch.config import MemoryConfig
from hm_arch.consolidation.replay import _l2_retention, _l3_retention
from hm_arch.types import EventType

from .prd_targets import (
    PRD_TARGETS,
    PrdPerformanceTargets,
    PrdTestBenchmarkTargets,
    PrdWeek9OptimizationTargets,
)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[idx]


def _set_old_created_at(db, memory_id: str, *, days_ago: int) -> None:
    old_time = (datetime.now(tz=timezone.utc) - timedelta(days=days_ago)).isoformat()
    db.execute(
        "UPDATE memory_index SET created_at = ? WHERE id = ?",
        (old_time, memory_id),
    )


def _benchmark_config(tmp_root: Path, *, replay_sample_ratio: float) -> MemoryConfig:
    return MemoryConfig(
        db_path=str(tmp_root / "prd_benchmark.db"),
        archive_root=str(tmp_root / "archives"),
        auto_consolidate=False,
        replay_sample_ratio=replay_sample_ratio,
    )


@dataclass
class BenchmarkReport:
    """Structured benchmark output for docs and CI artifacts."""

    environment: dict[str, Any]
    targets: dict[str, Any]
    results: dict[str, Any] = field(default_factory=dict)
    assertions: dict[str, bool] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "environment": self.environment,
                "targets": self.targets,
                "results": self.results,
                "assertions": self.assertions,
            },
            indent=2,
            default=str,
        )


def collect_environment() -> dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
    }


def measure_add_latency_ms(memory: HMArch, targets: PrdPerformanceTargets) -> dict[str, float]:
    for i in range(targets.add_warmup_iterations):
        memory.add(
            f"warmup episode {i} about python module",
            event_type=EventType.CODE,
        )
    samples: list[float] = []
    for i in range(targets.add_sample_iterations):
        t0 = time.perf_counter()
        memory.add(
            f"benchmark episode {i} refactored auth service",
            event_type=EventType.CODE,
            importance=0.6,
        )
        samples.append((time.perf_counter() - t0) * 1000.0)
    return {
        "p50_ms": statistics.median(samples),
        "p95_ms": _percentile(samples, 95),
        "samples": float(len(samples)),
    }


def seed_l2_episodes(memory: HMArch, count: int) -> float:
    t0 = time.perf_counter()
    for i in range(count):
        memory.add(
            f"User prefers Python on day {i % 30}; refactored auth module {i}",
            event_type=EventType.CODE if i % 3 else EventType.CONVERSATION,
            importance=0.5 + (i % 10) / 20.0,
        )
    return time.perf_counter() - t0


def measure_search_latency_ms(
    memory: HMArch, *, iterations: int
) -> dict[str, float]:
    samples: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        memory.search("user prefers python auth refactor", top_k=10)
        samples.append((time.perf_counter() - t0) * 1000.0)
    return {
        "p50_ms": statistics.median(samples),
        "p95_ms": _percentile(samples, 95),
        "samples": float(len(samples)),
    }


def _contract_row(observed: float, limit: float) -> dict[str, Any]:
    return {"observed": observed, "limit": limit, "pass": observed <= limit}


def build_contract_compliance(
    *,
    add_p95_ms: float,
    search_p95_ms: float,
    consolidate_seconds: float,
    storage_mb: float,
    test: PrdTestBenchmarkTargets,
    week9: PrdWeek9OptimizationTargets,
) -> dict[str, Any]:
    """Report pass/fail against both PRD performance tables."""
    return {
        "test_benchmark": {
            "add_p95_ms": _contract_row(add_p95_ms, test.add_p95_ms),
            "search_p95_ms": _contract_row(search_p95_ms, test.search_p95_ms),
            "consolidate_seconds": _contract_row(
                consolidate_seconds, test.consolidate_max_seconds
            ),
            "storage_mb": _contract_row(storage_mb, test.storage_max_mb),
        },
        "week9_optimization": {
            "add_p95_ms": _contract_row(add_p95_ms, week9.add_p95_ms),
            "search_p95_ms": _contract_row(search_p95_ms, week9.search_p95_ms),
            "consolidate_seconds": _contract_row(
                consolidate_seconds, week9.consolidate_max_seconds
            ),
        },
    }


def seed_l3_triples(memory: HMArch, count: int) -> None:
    """Insert *count* distinct active L3 rows (unique entity/relation keys)."""
    for i in range(count):
        memory._l3.upsert(f"entity_{i}", "knows", "python", confidence=0.9)


def run_seven_day_semantic_scenario(
    memory: HMArch, targets: PrdPerformanceTargets
) -> dict[str, Any]:
    """PRD 7-day scenario: 50 conversation events/day, nightly consolidate, L3 accuracy.

    Each conversation uses a unique ``(entity, relation)`` key so facts do not
    supersede one another. Expected triples are derived from episode text via the
    same offline :class:`~hm_arch.consolidation.replay.SemanticExtractor` rules.
    """
    conversations_per_day = targets.seven_day_conversations_per_day
    expected_triples: list[tuple[str, str, str]] = []
    consolidation_count = 0

    for day in range(targets.seven_day_consolidations):
        for i in range(conversations_per_day):
            entity = f"agent{day}_{i}"
            value = "Python"
            content = f"{entity.capitalize()} prefers {value}"
            expected_triples.append((entity, "prefers", value))
            memory_id = memory.add(
                content,
                event_type=EventType.CONVERSATION,
                importance=0.7,
            ).memory_id
            _set_old_created_at(memory._db, memory_id, days_ago=15 + day)

        memory.consolidate()
        consolidation_count += 1

    matched = 0
    for entity, relation, value in expected_triples:
        fact = memory._l3.get_by_entity_relation(entity, relation)
        if fact is not None and fact.value == value:
            matched += 1

    expected_count = len(expected_triples)
    accuracy = matched / expected_count if expected_count else 0.0

    return {
        "conversations_per_day": conversations_per_day,
        "total_conversations": expected_count,
        "consolidation_cycles": consolidation_count,
        "expected_semantic_facts": expected_count,
        "matched_semantic_facts": matched,
        "semantic_accuracy": accuracy,
        "l3_active_count": memory._l3.count(status="active"),
        "consolidation_log_rows": int(
            memory._db.query("SELECT COUNT(*) AS n FROM consolidation_log")[0]["n"]
        ),
    }


def run_l4_archive_10k_prd_scenario(
    memory: HMArch, targets: PrdPerformanceTargets
) -> dict[str, Any]:
    """Inject 10k L2 rows with mixed ages; expect L4 ≈ L2 × (1 − retention₃₀d).

    ~74% of episodes are back-dated beyond archive eligibility; ~26% remain near
    the 30-day PRD retention reference (~0.26) and stay active in L2.
    """
    l2_total = targets.l2_episode_count
    old_count = int(round(l2_total * targets.l4_archive_old_fraction))
    memory_ids: list[str] = []
    for i in range(l2_total):
        memory_id = memory.add(
            f"Long-run episodic memory {i}",
            event_type=EventType.CODE,
            importance=0.5,
        ).memory_id
        memory_ids.append(memory_id)

    for i, memory_id in enumerate(memory_ids):
        days_ago = (
            targets.l4_archive_old_days
            if i < old_count
            else targets.l4_archive_young_days
        )
        _set_old_created_at(memory._db, memory_id, days_ago=days_ago)

    report = memory.consolidate()
    archived_rows = int(
        memory._db.query(
            "SELECT COUNT(*) AS n FROM memory_index WHERE layer = 4 AND status = 'archived'"
        )[0]["n"]
    )
    active_l2 = int(
        memory._db.query(
            "SELECT COUNT(*) AS n FROM memory_index WHERE layer = 2 AND status = 'active'"
        )[0]["n"]
    )
    expected_archived = l2_total * (1.0 - targets.l2_retention_30d_reference)
    tolerance = max(1.0, expected_archived * targets.l4_archive_fraction_tolerance)
    low = expected_archived - tolerance
    high = expected_archived + tolerance

    return {
        "l2_total": l2_total,
        "old_episode_count": old_count,
        "young_episode_count": l2_total - old_count,
        "archived_l4_rows": archived_rows,
        "active_l2_rows": active_l2,
        "expected_archived_approx": expected_archived,
        "tolerance": tolerance,
        "expected_range": [low, high],
        "archived_to_l4_report": report.archived_to_l4,
        "archive_storage_mb": memory.get_stats().archive_storage_mb,
        "within_expected_range": low <= archived_rows <= high,
    }


def run_thirty_day_l4_archive_ratio_scenario(
    memory: HMArch, targets: PrdPerformanceTargets
) -> dict[str, Any]:
    """30-day coding-agent loop; archived L4 ≈ L2_episode_total × (1 − 0.26).

    Mirrors ``tests/test_simulation_30_day.py`` episode mix and nightly
    ``consolidate()`` cadence. Uses a wider relative tolerance than the
    deterministic 10k mixed-age inject (see ``thirty_day_l4_archive_tolerance_relative``).
    """
    preference_switch_day = 15
    for day in range(30):
        if day < preference_switch_day:
            pref_id = memory.add(
                "User prefers Python",
                event_type=EventType.CONVERSATION,
                importance=0.85,
            ).memory_id
            _set_old_created_at(memory._db, pref_id, days_ago=15 + day)
        elif day == preference_switch_day:
            memory.add(
                "User prefers TypeScript",
                event_type=EventType.CONVERSATION,
                importance=0.9,
            )
        code_id = memory.add(
            f"Refactored auth module on simulated day {day}",
            event_type=EventType.CODE,
            importance=0.55,
        ).memory_id
        _set_old_created_at(memory._db, code_id, days_ago=45 + day)
        memory.consolidate()

    l2_total = int(memory._db.query("SELECT COUNT(*) AS n FROM episodes")[0]["n"])
    archived_l4 = int(
        memory._db.query(
            "SELECT COUNT(*) AS n FROM memory_index WHERE layer = 4 AND status = 'archived'"
        )[0]["n"]
    )
    active_l2 = int(
        memory._db.query(
            "SELECT COUNT(*) AS n FROM memory_index WHERE layer = 2 AND status = 'active'"
        )[0]["n"]
    )
    expected_archived = l2_total * (1.0 - targets.l2_retention_30d_reference)
    tolerance_rel = targets.thirty_day_l4_archive_tolerance_relative
    if expected_archived > 0:
        relative_delta = abs(archived_l4 - expected_archived) / expected_archived
    else:
        relative_delta = 0.0 if archived_l4 == 0 else 1.0
    within_tolerance = relative_delta <= tolerance_rel
    return {
        "l2_episode_total": l2_total,
        "archived_l4_count": archived_l4,
        "active_l2_count": active_l2,
        "expected_archived_count": expected_archived,
        "archive_fraction_observed": archived_l4 / l2_total if l2_total else 0.0,
        "archive_fraction_expected": 1.0 - targets.l2_retention_30d_reference,
        "relative_delta": relative_delta,
        "tolerance_relative": tolerance_rel,
        "within_tolerance": within_tolerance,
    }


def run_l4_archive_scenario(memory: HMArch, *, episode_count: int = 200) -> dict[str, Any]:
    """Archive eligible stale L2 rows and measure L4 filesystem usage."""
    ids: list[str] = []
    for i in range(episode_count):
        mid = memory.add(
            f"Stale code change {i} in legacy auth",
            event_type=EventType.CODE,
            importance=0.4,
        ).memory_id
        ids.append(mid)
        _set_old_created_at(memory._db, mid, days_ago=90)
    report = memory.consolidate()
    stats = memory.get_stats()
    archived = memory._db.query(
        "SELECT COUNT(*) AS n FROM memory_index WHERE layer = 4 AND status = 'archived'"
    )[0]["n"]
    sample_retrievable = memory._l4.retrieve(ids[0]) is not None if ids else False
    return {
        "archived_to_l4": report.archived_to_l4,
        "archived_index_rows": int(archived),
        "archive_storage_mb": stats.archive_storage_mb,
        "sample_retrievable": sample_retrievable,
        "archive_file_count": len(memory._l4.list_archives()),
    }


def run_prd_benchmark_suite(
    tmp_root: Path,
    targets: PrdPerformanceTargets | None = None,
) -> BenchmarkReport:
    """Run the full PRD benchmark suite into an isolated directory."""
    targets = targets or PRD_TARGETS
    test_contract = targets.test_benchmark
    week9_contract = targets.week9_optimization
    report = BenchmarkReport(
        environment=collect_environment(),
        targets={
            **asdict(targets),
            "test_benchmark": asdict(test_contract),
            "week9_optimization": asdict(week9_contract),
        },
    )

    add_p95_ms = 0.0
    search_p95_ms = 0.0
    consolidate_seconds = 0.0
    storage_mb = 0.0

    # --- Latency: add (warm, modest corpus) ---------------------------------
    add_root = tmp_root / "add_latency"
    add_root.mkdir(parents=True, exist_ok=True)
    add_memory = HMArch(config=_benchmark_config(add_root, replay_sample_ratio=0.2))
    try:
        add_stats = measure_add_latency_ms(add_memory, targets)
        report.results["add_latency"] = add_stats
        add_p95_ms = add_stats["p95_ms"]
        report.assertions["test_benchmark_add_p95"] = (
            add_p95_ms <= test_contract.add_p95_ms
        )
        report.assertions["week9_add_p95"] = add_p95_ms <= week9_contract.add_p95_ms
    finally:
        add_memory.close()

    # --- Scale: 10k L2 + search + consolidate -------------------------------
    scale_root = tmp_root / "scale_10k"
    scale_root.mkdir(parents=True, exist_ok=True)
    scale_memory = HMArch(
        config=_benchmark_config(
            scale_root, replay_sample_ratio=targets.consolidate_replay_sample_ratio
        )
    )
    try:
        seed_seconds = seed_l2_episodes(scale_memory, targets.l2_episode_count)
        stats_after_l2 = scale_memory.get_stats()
        search_stats = measure_search_latency_ms(
            scale_memory, iterations=targets.search_sample_iterations
        )
        t0 = time.perf_counter()
        consolidate_report = scale_memory.consolidate()
        consolidate_wall = time.perf_counter() - t0

        report.results["l2_seed"] = {
            "episode_count": targets.l2_episode_count,
            "wall_seconds": seed_seconds,
            "storage_size_mb": stats_after_l2.storage_size_mb,
        }
        report.results["search_at_10k_l2"] = search_stats
        report.results["consolidate_at_10k_l2"] = {
            "wall_seconds": consolidate_wall,
            "duration_seconds": consolidate_report.duration_seconds,
            "extracted_semantics": consolidate_report.extracted_semantics,
            "merged_duplicates": consolidate_report.merged_duplicates,
            "archived_to_l4": consolidate_report.archived_to_l4,
            "scheduled_reviews": consolidate_report.scheduled_reviews,
        }
        search_p95_ms = search_stats["p95_ms"]
        consolidate_seconds = consolidate_wall
        report.assertions["test_benchmark_search_p95"] = (
            search_p95_ms <= test_contract.search_p95_ms
        )
        report.assertions["test_benchmark_consolidate_seconds"] = (
            consolidate_seconds <= test_contract.consolidate_max_seconds
        )
        report.assertions["week9_search_p95"] = (
            search_p95_ms <= week9_contract.search_p95_ms
        )
        report.assertions["week9_consolidate_seconds"] = (
            consolidate_seconds <= week9_contract.consolidate_max_seconds
        )
        report.assertions["consolidate_extracted_semantics"] = (
            consolidate_report.extracted_semantics >= 1
        )

        # --- Storage: add 5k L3 on same DB ------------------------------------
        seed_l3_triples(scale_memory, targets.l3_triple_count)
        stats_l2_l3 = scale_memory.get_stats()
        storage_mb = stats_l2_l3.storage_size_mb
        report.results["storage_10k_l2_5k_l3"] = {
            "l2_count": stats_l2_l3.by_layer[2],
            "l3_active_count": stats_l2_l3.by_layer[3],
            "storage_size_mb": storage_mb,
            "archive_storage_mb": stats_l2_l3.archive_storage_mb,
        }
        report.assertions["l2_count_at_least_10k"] = (
            stats_l2_l3.by_layer[2] >= targets.l2_episode_count
        )
        report.assertions["l3_count_at_least_5k"] = (
            stats_l2_l3.by_layer[3] >= targets.l3_triple_count
        )
        report.assertions["test_benchmark_storage_mb"] = (
            storage_mb < test_contract.storage_max_mb
        )

        # --- L4 smoke (small stale subset on same store) ---------------------
        l4_stats = run_l4_archive_scenario(scale_memory, episode_count=200)
        report.results["l4_archive_smoke"] = l4_stats
        report.assertions["l4_smoke_archived_rows"] = (
            l4_stats["archived_index_rows"] >= 1
        )
        report.assertions["l4_smoke_files_on_disk"] = l4_stats["archive_file_count"] >= 1
    finally:
        scale_memory.close()

    report.results["contract_compliance"] = build_contract_compliance(
        add_p95_ms=add_p95_ms,
        search_p95_ms=search_p95_ms,
        consolidate_seconds=consolidate_seconds,
        storage_mb=storage_mb,
        test=test_contract,
        week9=week9_contract,
    )

    # --- Seven-day semantic extraction (isolated DB) ------------------------
    seven_root = tmp_root / "seven_day"
    seven_root.mkdir(parents=True, exist_ok=True)
    seven_memory = HMArch(
        config=_benchmark_config(
            seven_root, replay_sample_ratio=targets.seven_day_replay_sample_ratio
        )
    )
    try:
        seven_stats = run_seven_day_semantic_scenario(seven_memory, targets)
        report.results["seven_day_semantic"] = seven_stats
        report.assertions["seven_day_semantic_accuracy"] = (
            seven_stats["semantic_accuracy"]
            >= targets.seven_day_min_semantic_accuracy
        )
        report.assertions["seven_day_consolidation_count"] = (
            seven_stats["consolidation_cycles"] == targets.seven_day_consolidations
        )
        report.assertions["seven_day_conversation_volume"] = (
            seven_stats["total_conversations"]
            == targets.seven_day_conversations_per_day * targets.seven_day_consolidations
        )
    finally:
        seven_memory.close()

    # --- L4 long-run archive @ 10k (isolated DB, PRD retention mix) ---------
    l4_root = tmp_root / "l4_archive_10k"
    l4_root.mkdir(parents=True, exist_ok=True)
    l4_memory = HMArch(
        config=_benchmark_config(l4_root, replay_sample_ratio=0.2)
    )
    try:
        l4_10k_stats = run_l4_archive_10k_prd_scenario(l4_memory, targets)
        report.results["l4_archive_10k_prd"] = l4_10k_stats
        report.assertions["l4_archive_10k_within_prd_range"] = l4_10k_stats[
            "within_expected_range"
        ]
    finally:
        l4_memory.close()

    # --- Retention reference (theoretical PRD, no simulation wall clock) ----
    cfg = MemoryConfig()
    report.results["retention_reference_30d"] = {
        "l2": _l2_retention(30 * 24, cfg),
        "l3": _l3_retention(30 * 24, cfg),
    }

    return report
