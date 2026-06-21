"""Synthetic offline fixtures for all benchmark families."""

from __future__ import annotations

from ..types import (
    BenchmarkFamily,
    BenchmarkQuery,
    IngestItem,
    SyntheticFixture,
)


def locomo_fixture() -> SyntheticFixture:
    """LoCoMo-style multi-session conversational memory QA."""
    ingest = (
        IngestItem(
            item_id="locomo-s1-u1",
            content="On 2024-03-01 Alice said she adopted a cat named Pixel.",
            session_id="session-1",
            metadata={"speaker": "alice", "date": "2024-03-01"},
        ),
        IngestItem(
            item_id="locomo-s1-u2",
            content="Bob replied that Pixel loves tuna treats.",
            session_id="session-1",
            metadata={"speaker": "bob"},
        ),
        IngestItem(
            item_id="locomo-s2-u1",
            content="On 2024-03-15 Alice moved from Boston to Seattle.",
            session_id="session-2",
            metadata={"speaker": "alice", "date": "2024-03-15"},
        ),
        IngestItem(
            item_id="locomo-s2-u2",
            content="Alice mentioned her new apartment is near Pike Place Market.",
            session_id="session-2",
            metadata={"speaker": "alice"},
        ),
    )
    queries = (
        BenchmarkQuery(
            query_id="locomo-q1",
            question="What is the name of Alice's cat?",
            expected_answer="Pixel",
            expected_memory_ids=("locomo-s1-u1",),
        ),
        BenchmarkQuery(
            query_id="locomo-q2",
            question="Which city does Alice live in now?",
            expected_answer="Seattle",
            expected_memory_ids=("locomo-s2-u1", "locomo-s2-u2"),
        ),
    )
    return SyntheticFixture(
        family=BenchmarkFamily.LOCOMO,
        ingest_items=ingest,
        queries=queries,
        consolidate_after_ingest=True,
    )


def tau2_bench_fixture() -> SyntheticFixture:
    """tau2-bench-style task success with structured task logs."""
    ingest = (
        IngestItem(
            item_id="tau2-task-log-1",
            content="Task: book_restaurant. Status: completed. Restaurant: Sakura Sushi.",
            session_id="task-run-1",
            metadata={"task": "book_restaurant", "status": "completed"},
        ),
        IngestItem(
            item_id="tau2-task-log-2",
            content="Task: send_email. Status: failed. Reason: invalid recipient.",
            session_id="task-run-2",
            metadata={"task": "send_email", "status": "failed"},
        ),
        IngestItem(
            item_id="tau2-task-log-3",
            content="Task: book_restaurant. Status: completed. Restaurant: Green Bowl.",
            session_id="task-run-3",
            metadata={"task": "book_restaurant", "status": "completed"},
        ),
    )
    queries = (
        BenchmarkQuery(
            query_id="tau2-q1",
            question="Did the restaurant booking task succeed for Sakura Sushi?",
            expected_answer="yes",
            expected_memory_ids=("tau2-task-log-1",),
            task_success_criteria="completed",
        ),
        BenchmarkQuery(
            query_id="tau2-q2",
            question="What was the failure reason for the email task?",
            expected_answer="invalid recipient",
            expected_memory_ids=("tau2-task-log-2",),
            task_success_criteria="failed",
        ),
    )
    return SyntheticFixture(
        family=BenchmarkFamily.TAU2_BENCH,
        ingest_items=ingest,
        queries=queries,
        consolidate_after_ingest=False,
    )


def hotpotqa_fixture() -> SyntheticFixture:
    """HotpotQA-style multi-hop QA with supporting facts (pinned v1 subset)."""
    from .hotpotqa import get_hotpotqa_fixture

    return get_hotpotqa_fixture()


_FIXTURES: dict[BenchmarkFamily, SyntheticFixture] = {
    BenchmarkFamily.LOCOMO: locomo_fixture(),
    BenchmarkFamily.TAU2_BENCH: tau2_bench_fixture(),
    BenchmarkFamily.HOTPOTQA: hotpotqa_fixture(),
}


def get_synthetic_fixture(family: BenchmarkFamily) -> SyntheticFixture:
    return _FIXTURES[family]


def all_synthetic_fixtures() -> tuple[SyntheticFixture, ...]:
    return tuple(_FIXTURES[family] for family in BenchmarkFamily)
