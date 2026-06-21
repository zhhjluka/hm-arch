"""Cross-agent benchmark harness orchestration."""

from __future__ import annotations

import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agents.cli_runner import AgentRunnerContext
from .agents.hm_arch_bench import agent_prompt_context, agent_uses_hook_recall
from .agents.registry import create_agent_runner, is_supported_coordinate
from .agents.workspace import AgentWorkspace
from .backends.registry import create_memory_backend
from .checkpoint import (
    load_checkpoint,
    mark_phase,
    phase_done,
    write_checkpoint,
)
from .compatibility import compatibility_snapshot, lookup_matrix_cell
from .fixtures.synthetic import get_synthetic_fixture
from .failure_provenance import build_query_failure_provenance
from .metrics import (
    aggregate_query_records,
    exact_match_accuracy,
    retrieval_hit_rate,
)
from .output import (
    append_query_jsonl,
    default_output_paths,
    prepare_run_directory,
    write_queries_csv,
    write_queries_jsonl,
    write_summary_json,
)
from .protocol import AgentRunner, MemoryBackend
from .run_id import resolve_run_id
from .types import (
    AgentOutcome,
    BenchmarkFamily,
    BenchmarkQuery,
    BenchmarkRunConfig,
    BenchmarkRunResult,
    QueryRecord,
    RecallOutcome,
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
        input_token_source=str(row.get("input_token_source", "estimated")),
        output_token_source=str(row.get("output_token_source", "estimated")),
        failure_count=int(row["failure_count"]),
        retrieved_ids=tuple(row.get("retrieved_ids", ())),
        expected_memory_ids=tuple(row.get("expected_memory_ids", ())),
        recall_context_chars=int(row.get("recall_context_chars", 0)),
        recall_hit_count=int(row.get("recall_hit_count", 0)),
        agent_managed=bool(row.get("agent_managed", False)),
        failure_reason=row.get("failure_reason"),
        failure_category=row.get("failure_category"),
        recall_failure_reason=row.get("recall_failure_reason"),
        agent_failure_reason=row.get("agent_failure_reason"),
        agent_exit_code=row.get("agent_exit_code"),
        agent_timed_out=row.get("agent_timed_out"),
    )


def _checkpoint_config_matches(
    checkpoint: dict[str, Any], config: BenchmarkRunConfig
) -> bool:
    stored = checkpoint.get("config")
    if not stored:
        return True
    return stored == config.to_dict()


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
        output_root = self.output_root.resolve()
        paths = default_output_paths(output_root, run_id)
        prepare_run_directory(paths, resume=config.resume)
        storage_dir = paths["run_dir"] / "storage"
        storage_dir.mkdir(parents=True, exist_ok=True)

        matrix_cell = lookup_matrix_cell(config.agent, config.backend)
        supported, support_rationale = is_supported_coordinate(config)

        workspace: AgentWorkspace | None = None
        if not config.use_mock_agent:
            workspace = AgentWorkspace.create(
                config.agent,
                run_id=run_id,
                parent=paths["run_dir"],
            )

        agent_context = AgentRunnerContext(
            workspace=workspace or AgentWorkspace.create(
                config.agent,
                run_id=run_id,
                parent=paths["run_dir"],
            ),
            config=config,
            storage_dir=storage_dir,
            executable=config.agent_executable,
            metadata={
                "matrix_implementation": matrix_cell.implementation.value,
                "matrix_rationale": matrix_cell.rationale,
            },
        )

        phases_completed: list[str] = []
        completed_query_ids: list[str] = []
        query_records: list[QueryRecord] = []
        backend_opened = False
        agent_opened = False
        run_error: str | None = None

        if config.resume:
            checkpoint = load_checkpoint(storage_dir)
            if (
                checkpoint
                and checkpoint.get("run_id") == run_id
                and _checkpoint_config_matches(checkpoint, config)
            ):
                phases_completed = list(checkpoint.get("phases_completed", []))
                completed_query_ids = list(checkpoint.get("completed_query_ids", []))
                query_records = [
                    _query_record_from_checkpoint(row)
                    for row in checkpoint.get("queries", [])
                ]

        environment = collect_environment()
        agent_metadata: dict[str, Any] = {
            "matrix_implementation": matrix_cell.implementation.value,
            "matrix_rationale": matrix_cell.rationale,
            "support_rationale": support_rationale,
            "supported": supported,
            "use_mock_agent": config.use_mock_agent,
        }
        if workspace is not None:
            agent_metadata["agent_home"] = str(workspace.agent_home)
            agent_metadata["workspace_root"] = str(workspace.root)
        agent_metadata["storage_dir"] = str(storage_dir)

        if not supported:
            aggregates = aggregate_query_records([])
            result = BenchmarkRunResult(
                run_id=run_id,
                config=config,
                storage_dir=str(storage_dir),
                phases_completed=[RunPhase.SETUP.value],
                queries=[],
                aggregates=aggregates,
                environment=environment,
                agent_metadata={
                    **agent_metadata,
                    "error": support_rationale,
                    "status": "unsupported",
                },
                compatibility=compatibility_snapshot(),
            )
            write_summary_json(paths["summary_json"], result)
            write_queries_csv(paths["queries_csv"], result)
            if workspace is not None:
                workspace.cleanup()
            return result

        backend = self._backend or create_memory_backend(config.backend, agent=config.agent)
        agent = self._agent or create_agent_runner(config.agent, context=agent_context)

        try:
            if not phase_done(phases_completed, RunPhase.SETUP):
                try:
                    agent.open()
                    agent_opened = True
                    agent_metadata.update(agent_context.metadata)
                    backend.open(storage_dir, config)
                    backend_opened = True
                except NotImplementedError as exc:
                    aggregates = aggregate_query_records([])
                    result = BenchmarkRunResult(
                        run_id=run_id,
                        config=config,
                        storage_dir=str(storage_dir),
                        phases_completed=[RunPhase.SETUP.value],
                        queries=[],
                        aggregates=aggregates,
                        environment=environment,
                        agent_metadata={
                            **agent_metadata,
                            "error": str(exc),
                            "status": "unsupported",
                        },
                        compatibility=compatibility_snapshot(),
                    )
                    write_summary_json(paths["summary_json"], result)
                    write_queries_csv(paths["queries_csv"], result)
                    if agent_opened:
                        agent.close()
                    if workspace is not None:
                        workspace.cleanup()
                    return result
                mark_phase(phases_completed, RunPhase.SETUP)
                self._persist_checkpoint(
                    storage_dir,
                    run_id=run_id,
                    config=config,
                    phases_completed=phases_completed,
                    completed_query_ids=completed_query_ids,
                    query_records=query_records,
                )
            elif not backend_opened:
                agent.open()
                agent_opened = True
                backend.open(storage_dir, config)
                backend_opened = True

            if not phase_done(phases_completed, RunPhase.INGEST):
                self._run_ingest(backend, fixture)
                mark_phase(phases_completed, RunPhase.INGEST)
                self._persist_checkpoint(
                    storage_dir,
                    run_id=run_id,
                    config=config,
                    phases_completed=phases_completed,
                    completed_query_ids=completed_query_ids,
                    query_records=query_records,
                )

            if fixture.consolidate_after_ingest and not phase_done(
                phases_completed, RunPhase.CONSOLIDATE
            ):
                backend.consolidate()
                mark_phase(phases_completed, RunPhase.CONSOLIDATE)
                self._persist_checkpoint(
                    storage_dir,
                    run_id=run_id,
                    config=config,
                    phases_completed=phases_completed,
                    completed_query_ids=completed_query_ids,
                    query_records=query_records,
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
                    self._persist_checkpoint(
                        storage_dir,
                        run_id=run_id,
                        config=config,
                        phases_completed=phases_completed,
                        completed_query_ids=completed_query_ids,
                        query_records=query_records,
                    )
                mark_phase(phases_completed, RunPhase.QUERY)

            if not phase_done(phases_completed, RunPhase.EVALUATE):
                mark_phase(phases_completed, RunPhase.EVALUATE)
                self._persist_checkpoint(
                    storage_dir,
                    run_id=run_id,
                    config=config,
                    phases_completed=phases_completed,
                    completed_query_ids=completed_query_ids,
                    query_records=query_records,
                )

        except Exception as exc:
            run_error = str(exc)
            self._persist_checkpoint(
                storage_dir,
                run_id=run_id,
                config=config,
                phases_completed=phases_completed,
                completed_query_ids=completed_query_ids,
                query_records=query_records,
                status="failed",
                error=run_error,
            )
            raise
        finally:
            if backend_opened:
                backend.close()
            if agent_opened:
                agent.close()
            if run_error is not None and workspace is not None:
                workspace.cleanup()
            if run_error is None and not phase_done(phases_completed, RunPhase.TEARDOWN):
                mark_phase(phases_completed, RunPhase.TEARDOWN)

        aggregates = aggregate_query_records(query_records)
        result = BenchmarkRunResult(
            run_id=run_id,
            config=config,
            storage_dir=str(storage_dir),
            phases_completed=phases_completed,
            queries=query_records,
            aggregates=aggregates,
            environment=environment,
            agent_metadata=agent_metadata,
            compatibility=compatibility_snapshot(),
        )

        mark_phase(phases_completed, RunPhase.CHECKPOINT)
        self._persist_checkpoint(
            storage_dir,
            run_id=run_id,
            config=config,
            phases_completed=phases_completed,
            completed_query_ids=completed_query_ids,
            query_records=query_records,
            status="completed",
        )
        write_queries_jsonl(paths["queries_jsonl"], query_records, run_id=run_id)
        write_summary_json(paths["summary_json"], result)
        write_queries_csv(paths["queries_csv"], result)
        if workspace is not None:
            workspace.cleanup()
        return result

    def _persist_checkpoint(
        self,
        storage_dir: Path,
        *,
        run_id: str,
        config: BenchmarkRunConfig,
        phases_completed: list[str],
        completed_query_ids: list[str],
        query_records: list[QueryRecord],
        status: str = "in_progress",
        error: str | None = None,
    ) -> None:
        write_checkpoint(
            storage_dir,
            run_id=run_id,
            phases_completed=phases_completed,
            completed_query_ids=completed_query_ids,
            queries=query_records,
            config=config,
            status=status,
            error=error,
        )

    def _run_ingest(self, backend: MemoryBackend, fixture: SyntheticFixture) -> None:
        for item in fixture.ingest_items:
            backend.ingest(item)

    def _run_query(
        self,
        *,
        config: BenchmarkRunConfig,
        fixture: SyntheticFixture,
        backend: MemoryBackend,
        agent: AgentRunner,
        query: BenchmarkQuery,
    ) -> QueryRecord:
        hook_managed = self._agent_hook_managed_recall(agent, config)
        t0 = time.perf_counter()
        if hook_managed:
            recall = RecallOutcome(
                context="",
                retrieved_ids=(),
                recall_time_ms=0.0,
                context_chars=0,
                hit_count=0,
                agent_managed=True,
            )
        else:
            recall = self._safe_recall(backend, query, top_k=config.top_k)

        prompt_context = agent_prompt_context(
            config,
            recall.context,
            hook_managed=hook_managed,
        )
        agent_out = self._safe_answer(
            agent,
            query,
            prompt_context,
            seed=config.seed,
        )
        if hook_managed:
            total_ms = agent_out.agent_time_ms
        else:
            total_ms = (time.perf_counter() - t0) * 1000.0
        accuracy = exact_match_accuracy(query.expected_answer, agent_out.answer)
        hit_rate = (
            None
            if hook_managed
            else retrieval_hit_rate(recall.retrieved_ids, query.expected_memory_ids)
        )
        failure_count = recall.failure_count + agent_out.failure_count
        failure_fields = build_query_failure_provenance(recall=recall, agent_out=agent_out)

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
            input_token_source=agent_out.input_token_source,
            output_token_source=agent_out.output_token_source,
            failure_count=failure_count,
            retrieved_ids=recall.retrieved_ids,
            expected_memory_ids=query.expected_memory_ids,
            recall_context_chars=recall.context_chars,
            recall_hit_count=recall.hit_count,
            agent_managed=hook_managed or recall.agent_managed,
            **failure_fields,
        )

    @staticmethod
    def _agent_hook_managed_recall(agent: AgentRunner, config: BenchmarkRunConfig) -> bool:
        if config.use_mock_agent:
            return False
        hook_managed = getattr(agent, "hook_managed_recall", None)
        if callable(hook_managed):
            return bool(hook_managed())
        return agent_uses_hook_recall(config)

    def _safe_recall(
        self,
        backend: MemoryBackend,
        query: BenchmarkQuery,
        *,
        top_k: int,
    ) -> RecallOutcome:
        t0 = time.perf_counter()
        try:
            return backend.recall(query, top_k=top_k)
        except Exception as exc:  # noqa: BLE001 — count adapter failures per query
            elapsed = (time.perf_counter() - t0) * 1000.0
            return RecallOutcome(
                context="",
                retrieved_ids=(),
                recall_time_ms=elapsed,
                failure_count=1,
                error=str(exc),
            )

    def _safe_answer(
        self,
        agent: AgentRunner,
        query: BenchmarkQuery,
        recalled_context: str,
        *,
        seed: int,
    ) -> AgentOutcome:
        t0 = time.perf_counter()
        try:
            return agent.answer(
                query,
                recalled_context=recalled_context,
                seed=seed,
            )
        except Exception as exc:  # noqa: BLE001 — count adapter failures per query
            elapsed = (time.perf_counter() - t0) * 1000.0
            return AgentOutcome(
                answer="",
                task_success=False if query.task_success_criteria is not None else None,
                input_tokens=0,
                output_tokens=0,
                agent_time_ms=elapsed,
                failure_count=1,
                error=str(exc),
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
            use_mock_agent=True,
        )
        results.append(harness.run(config))
    return results
