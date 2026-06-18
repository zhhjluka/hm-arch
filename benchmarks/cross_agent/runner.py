"""Cross-agent benchmark harness orchestration."""

from __future__ import annotations

import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agents.registry import create_agent_runner
from .backends.registry import create_memory_backend
from .checkpoint import (
    load_checkpoint,
    mark_phase,
    phase_done,
    write_checkpoint,
)
from .fixtures.synthetic import get_synthetic_fixture
from .metrics import (
    aggregate_query_records,
    exact_match_accuracy,
    retrieval_hit_rate,
)
from .output import (
    append_query_jsonl,
    default_output_paths,
    write_queries_csv,
    write_summary_json,
)
from .protocol import AgentRunner, MemoryBackend
from .run_id import resolve_run_id
from .types import (
    AgentOutcome,
    BenchmarkFamily,
    BenchmarkRunConfig,
    BenchmarkRunResult,
    QueryRecord,
    RunPhase,
    SyntheticFixture,
)


def collect_environment() -> dict[str, str]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
    }


def _query_record_from_checkpoint(row: dict[str, Any]) -> QueryRecord:
    return QueryRecord(
        query_id=row["query_id"],
        family=row["family"],
        question=row["question"],
        expected_answer=row.get("expected_answer"),
        prediction=row.get("prediction"),
        accuracy=row.get("accuracy"),
        task_success=row.get("task_success"),
        retrieval_hit_rate=row.get("retrieval_hit_rate"),
        recall_time_ms=float(row["recall_time_ms"]),
        agent_time_ms=float(row["agent_time_ms"]),
        query_time_ms=float(row["query_time_ms"]),
        input_tokens=int(row["input_tokens"]),
        output_tokens=int(row["output_tokens"]),
        failure_count=int(row["failure_count"]),
        retrieved_ids=tuple(row.get("retrieved_ids", ())),
        expected_memory_ids=tuple(row.get("expected_memory_ids", ())),
    )


class CrossAgentBenchmarkHarness:
    """Execute ingest → consolidate → query lifecycle with checkpoint/resume."""

    def __init__(
        self,
        *,
        output_root: Path,
        backend: MemoryBackend | None = None,
        agent: AgentRunner | None = None,
    ) -> None:
        self.output_root = output_root
        self._backend = backend
        self._agent = agent

    def run(self, config: BenchmarkRunConfig) -> BenchmarkRunResult:
        run_id = resolve_run_id(config)
        fixture = get_synthetic_fixture(config.family)
        paths = default_output_paths(self.output_root, run_id)
        storage_dir = paths["run_dir"] / "storage"
        storage_dir.mkdir(parents=True, exist_ok=True)

        agent = self._agent or create_agent_runner(config.agent)
        backend = self._backend or create_memory_backend(
            config.backend,
            config,
            native_bridge=getattr(agent, "native_memory_bridge", lambda: None)(),
        )

        phases_completed: list[str] = []
        completed_query_ids: list[str] = []
        query_records: list[QueryRecord] = []

        if config.resume:
            checkpoint = load_checkpoint(storage_dir)
            if checkpoint and checkpoint.get("run_id") == run_id:
                phases_completed = list(checkpoint.get("phases_completed", []))
                completed_query_ids = list(checkpoint.get("completed_query_ids", []))
                query_records = [
                    _query_record_from_checkpoint(row)
                    for row in checkpoint.get("queries", [])
                ]

        environment = collect_environment()

        if not phase_done(phases_completed, RunPhase.SETUP):
            backend.open(storage_dir, config)
            mark_phase(phases_completed, RunPhase.SETUP)
            write_checkpoint(
                storage_dir,
                run_id=run_id,
                phases_completed=phases_completed,
                completed_query_ids=completed_query_ids,
                queries=query_records,
            )

        if not phase_done(phases_completed, RunPhase.INGEST):
            self._run_ingest(backend, fixture)
            mark_phase(phases_completed, RunPhase.INGEST)
            write_checkpoint(
                storage_dir,
                run_id=run_id,
                phases_completed=phases_completed,
                completed_query_ids=completed_query_ids,
                queries=query_records,
            )

        if fixture.consolidate_after_ingest and not phase_done(
            phases_completed, RunPhase.CONSOLIDATE
        ):
            backend.consolidate()
            mark_phase(phases_completed, RunPhase.CONSOLIDATE)
            write_checkpoint(
                storage_dir,
                run_id=run_id,
                phases_completed=phases_completed,
                completed_query_ids=completed_query_ids,
                queries=query_records,
            )

        if not phase_done(phases_completed, RunPhase.QUERY):
            for query in fixture.queries:
                if query.query_id in completed_query_ids:
                    continue
                record = self._run_query(
                    config=config,
                    fixture=fixture,
                    backend=backend,
                    agent=agent,
                    query=query,
                )
                query_records.append(record)
                completed_query_ids.append(query.query_id)
                append_query_jsonl(paths["queries_jsonl"], record, run_id=run_id)
                write_checkpoint(
                    storage_dir,
                    run_id=run_id,
                    phases_completed=phases_completed,
                    completed_query_ids=completed_query_ids,
                    queries=query_records,
                )
            mark_phase(phases_completed, RunPhase.QUERY)

        if not phase_done(phases_completed, RunPhase.EVALUATE):
            mark_phase(phases_completed, RunPhase.EVALUATE)
            write_checkpoint(
                storage_dir,
                run_id=run_id,
                phases_completed=phases_completed,
                completed_query_ids=completed_query_ids,
                queries=query_records,
            )

        if not phase_done(phases_completed, RunPhase.TEARDOWN):
            provider_artifacts = None
            if hasattr(backend, "provider_artifacts"):
                provider_artifacts = backend.provider_artifacts()
            backend.close()
            mark_phase(phases_completed, RunPhase.TEARDOWN)
        else:
            provider_artifacts = None
            if hasattr(backend, "provider_artifacts"):
                provider_artifacts = backend.provider_artifacts()

        aggregates = aggregate_query_records(query_records)
        result = BenchmarkRunResult(
            run_id=run_id,
            config=config,
            storage_dir=str(storage_dir),
            phases_completed=phases_completed,
            queries=query_records,
            aggregates=aggregates,
            environment=environment,
            provider_artifacts=provider_artifacts,
        )

        mark_phase(phases_completed, RunPhase.CHECKPOINT)
        write_checkpoint(
            storage_dir,
            run_id=run_id,
            phases_completed=phases_completed,
            completed_query_ids=completed_query_ids,
            queries=query_records,
        )
        write_summary_json(paths["summary_json"], result)
        write_queries_csv(paths["queries_csv"], result)
        return result

    def _run_ingest(self, backend: MemoryBackend, fixture: SyntheticFixture) -> None:
        for item in fixture.ingest_items:
            outcome = backend.ingest(item)
            if outcome.failure_count:
                raise RuntimeError(
                    f"Ingest failed for item {item.item_id}: {outcome.error}"
                )

    def _run_query(
        self,
        *,
        config: BenchmarkRunConfig,
        fixture: SyntheticFixture,
        backend: MemoryBackend,
        agent: AgentRunner,
        query,
    ) -> QueryRecord:
        t0 = time.perf_counter()
        recall = backend.recall(query, top_k=config.top_k)
        agent_out: AgentOutcome = agent.answer(
            query,
            recalled_context=recall.context,
            seed=config.seed,
        )
        total_ms = (time.perf_counter() - t0) * 1000.0
        accuracy = exact_match_accuracy(query.expected_answer, agent_out.answer)
        hit_rate = retrieval_hit_rate(recall.retrieved_ids, query.expected_memory_ids)
        failure_count = recall.failure_count + agent_out.failure_count

        return QueryRecord(
            query_id=query.query_id,
            family=fixture.family.value,
            question=query.question,
            expected_answer=query.expected_answer,
            prediction=agent_out.answer,
            accuracy=accuracy,
            task_success=agent_out.task_success,
            retrieval_hit_rate=hit_rate,
            recall_time_ms=recall.recall_time_ms,
            agent_time_ms=agent_out.agent_time_ms,
            query_time_ms=total_ms,
            input_tokens=agent_out.input_tokens,
            output_tokens=agent_out.output_tokens,
            failure_count=failure_count,
            retrieved_ids=recall.retrieved_ids,
            expected_memory_ids=query.expected_memory_ids,
        )


def run_cross_agent_benchmark(
    config: BenchmarkRunConfig,
    *,
    output_root: Path,
) -> BenchmarkRunResult:
    """Convenience entry point for a single configured run."""
    return CrossAgentBenchmarkHarness(output_root=output_root).run(config)


def run_synthetic_matrix(
    *,
    output_root: Path,
    families: tuple[BenchmarkFamily, ...] | None = None,
    backend=None,
    agent=None,
) -> list[BenchmarkRunResult]:
    """Run the offline synthetic fixture across benchmark families."""
    from .types import AgentKind, MemoryBackendKind

    families = families or tuple(BenchmarkFamily)
    harness = CrossAgentBenchmarkHarness(
        output_root=output_root,
        backend=backend,
        agent=agent,
    )
    results: list[BenchmarkRunResult] = []
    for family in families:
        config = BenchmarkRunConfig(
            family=family,
            agent=AgentKind.CODEX,
            backend=MemoryBackendKind.HM_ARCH,
            seed=0,
            resume=False,
        )
        results.append(harness.run(config))
    return results
