"""Offline smoke fixtures — not real tau2-bench data (HM-76 / MEM-76)."""

from __future__ import annotations

from ..types import BenchmarkFamily, BenchmarkQuery, IngestItem, SyntheticFixture
from .config import Tau2Domain

SMOKE_FIXTURE_LABEL = "synthetic_smoke"


def retail_smoke_fixture() -> SyntheticFixture:
    """Labeled synthetic retail smoke fixture."""
    ingest = (
        IngestItem(
            item_id="retail-task-1",
            content=(
                "Task: lookup_order. Status: completed. "
                "Order ORD-4821 for wireless earbuds, delivery confirmed."
            ),
            session_id="retail-run-1",
            metadata={"domain": "retail", "task": "lookup_order", "status": "completed", "fixture_source": SMOKE_FIXTURE_LABEL},
        ),
        IngestItem(
            item_id="retail-task-2",
            content=(
                "Task: initiate_return. Status: completed. "
                "Return label issued for order ORD-4821, reason: wrong color."
            ),
            session_id="retail-run-2",
            metadata={"domain": "retail", "task": "initiate_return", "status": "completed", "fixture_source": SMOKE_FIXTURE_LABEL},
        ),
        IngestItem(
            item_id="retail-task-3",
            content=(
                "Task: process_refund. Status: failed. "
                "Reason: payment gateway timeout after return received."
            ),
            session_id="retail-run-3",
            metadata={"domain": "retail", "task": "process_refund", "status": "failed", "fixture_source": SMOKE_FIXTURE_LABEL},
        ),
        IngestItem(
            item_id="retail-task-4",
            content=(
                "Task: update_shipping_address. Status: completed. "
                "Order ORD-5102 rerouted to 221B Baker Street."
            ),
            session_id="retail-run-4",
            metadata={"domain": "retail", "task": "update_shipping_address", "status": "completed", "fixture_source": SMOKE_FIXTURE_LABEL},
        ),
    )
    queries = (
        BenchmarkQuery(
            query_id="retail-q1",
            question="Did the return initiation for order ORD-4821 succeed?",
            expected_answer="yes",
            expected_memory_ids=("retail-task-2",),
            task_success_criteria="completed",
            metadata={"domain": "retail", "fixture_source": SMOKE_FIXTURE_LABEL},
        ),
        BenchmarkQuery(
            query_id="retail-q2",
            question="What was the failure reason for the refund task?",
            expected_answer="payment gateway timeout",
            expected_memory_ids=("retail-task-3",),
            task_success_criteria="failed",
            metadata={"domain": "retail", "fixture_source": SMOKE_FIXTURE_LABEL},
        ),
        BenchmarkQuery(
            query_id="retail-q3",
            question="What shipping address was applied to order ORD-5102?",
            expected_answer="221B Baker Street",
            expected_memory_ids=("retail-task-4",),
            task_success_criteria="completed",
            metadata={"domain": "retail", "fixture_source": SMOKE_FIXTURE_LABEL},
        ),
    )
    return SyntheticFixture(
        family=BenchmarkFamily.TAU2_BENCH,
        ingest_items=ingest,
        queries=queries,
        consolidate_after_ingest=False,
    )


def airline_smoke_fixture() -> SyntheticFixture:
    """Labeled synthetic airline smoke fixture."""
    ingest = (
        IngestItem(
            item_id="airline-task-1",
            content=(
                "Task: change_flight. Status: completed. "
                "Flight AA204 moved from 2024-06-10 to 2024-06-12."
            ),
            session_id="airline-run-1",
            metadata={"domain": "airline", "task": "change_flight", "status": "completed", "fixture_source": SMOKE_FIXTURE_LABEL},
        ),
        IngestItem(
            item_id="airline-task-2",
            content=(
                "Task: select_seat. Status: completed. "
                "Seat 14C confirmed on flight AA204."
            ),
            session_id="airline-run-2",
            metadata={"domain": "airline", "task": "select_seat", "status": "completed", "fixture_source": SMOKE_FIXTURE_LABEL},
        ),
        IngestItem(
            item_id="airline-task-3",
            content=(
                "Task: cancel_booking. Status: failed. "
                "Reason: non-refundable fare without travel insurance."
            ),
            session_id="airline-run-3",
            metadata={"domain": "airline", "task": "cancel_booking", "status": "failed", "fixture_source": SMOKE_FIXTURE_LABEL},
        ),
        IngestItem(
            item_id="airline-task-4",
            content=(
                "Task: add_baggage. Status: completed. "
                "One checked bag added to confirmation PNR-XK91."
            ),
            session_id="airline-run-4",
            metadata={"domain": "airline", "task": "add_baggage", "status": "completed", "fixture_source": SMOKE_FIXTURE_LABEL},
        ),
    )
    queries = (
        BenchmarkQuery(
            query_id="airline-q1",
            question="Was the flight change for AA204 completed successfully?",
            expected_answer="yes",
            expected_memory_ids=("airline-task-1",),
            task_success_criteria="completed",
            metadata={"domain": "airline", "fixture_source": SMOKE_FIXTURE_LABEL},
        ),
        BenchmarkQuery(
            query_id="airline-q2",
            question="What seat was confirmed on flight AA204?",
            expected_answer="14C",
            expected_memory_ids=("airline-task-2",),
            task_success_criteria="completed",
            metadata={"domain": "airline", "fixture_source": SMOKE_FIXTURE_LABEL},
        ),
        BenchmarkQuery(
            query_id="airline-q3",
            question="Why did the booking cancellation fail?",
            expected_answer="non-refundable fare without travel insurance",
            expected_memory_ids=("airline-task-3",),
            task_success_criteria="failed",
            metadata={"domain": "airline", "fixture_source": SMOKE_FIXTURE_LABEL},
        ),
    )
    return SyntheticFixture(
        family=BenchmarkFamily.TAU2_BENCH,
        ingest_items=ingest,
        queries=queries,
        consolidate_after_ingest=False,
    )


_SMOKE_FIXTURES: dict[Tau2Domain, SyntheticFixture] = {
    Tau2Domain.RETAIL: retail_smoke_fixture(),
    Tau2Domain.AIRLINE: airline_smoke_fixture(),
}


def get_smoke_domain_fixture(domain: Tau2Domain) -> SyntheticFixture:
    return _SMOKE_FIXTURES[domain]
