"""Shared smoke conversation dataset for cross-agent agent-runner tests."""

from __future__ import annotations

from benchmarks.cross_agent.types import BenchmarkFamily, BenchmarkQuery, IngestItem, SyntheticFixture

SMOKE_DATASET_ID = "cross-agent-smoke-v1"

SMOKE_FIXTURE = SyntheticFixture(
    family=BenchmarkFamily.LOCOMO,
    ingest_items=(
        IngestItem(
            item_id="intro",
            content="My name is Alex and I prefer Python for backend services.",
            session_id="smoke-s1",
        ),
        IngestItem(
            item_id="project-context",
            content="We are building hm-arch offline benchmarks with isolated agent homes.",
            session_id="smoke-s1",
        ),
    ),
    queries=(
        BenchmarkQuery(
            query_id="preference-recall",
            question="What language do I prefer for backend services?",
            expected_answer="Python",
            expected_memory_ids=("intro",),
        ),
        BenchmarkQuery(
            query_id="project-recall",
            question="What project context did I mention?",
            expected_answer="hm-arch offline benchmarks with isolated agent homes",
            expected_memory_ids=("project-context",),
        ),
    ),
    consolidate_after_ingest=True,
)
