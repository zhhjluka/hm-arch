"""Load version-pinned tau2-bench tasks and build harness fixtures."""

from __future__ import annotations

from typing import Any

from ..types import BenchmarkFamily, BenchmarkQuery, IngestItem, SyntheticFixture
from .availability import ensure_tau2_data_dir, require_tau2
from .config import Tau2Domain
from .environment_runner import (
    GOLD_REPLAY_HARNESS_LABEL,
    Tau2EnvironmentExecution,
    execute_domain_tasks,
)
from .pin import DEFAULT_NUM_TASKS, DEFAULT_TASK_SPLIT, provenance

REAL_FIXTURE_LABEL = "tau2_bench_v1.0.0"


def load_tau2_tasks(
    domain: Tau2Domain,
    *,
    task_split_name: str = DEFAULT_TASK_SPLIT,
    num_tasks: int = DEFAULT_NUM_TASKS,
    task_ids: list[str] | None = None,
) -> list[Any]:
    """Load real tau2-bench tasks for *domain*."""
    data_dir = ensure_tau2_data_dir()
    require_tau2()
    import tau2.utils.utils as tau2_utils

    tau2_utils.DATA_DIR = data_dir
    from tau2.runner.helpers import get_tasks

    return get_tasks(
        domain.value,
        task_split_name=task_split_name,
        task_ids=task_ids,
        num_tasks=None if task_ids else num_tasks,
    )


def _task_reason_for_call(task) -> str:
    scenario = task.user_scenario
    instructions = getattr(scenario, "instructions", None)
    if instructions is None:
        return str(scenario)
    if hasattr(instructions, "reason_for_call"):
        return str(instructions.reason_for_call)
    if isinstance(instructions, dict):
        return str(instructions.get("reason_for_call", instructions))
    return str(instructions)


def _execution_summary(execution: Tau2EnvironmentExecution) -> str:
    action_names = [step.tool_name for step in execution.action_steps]
    status = "completed" if execution.task_success else "failed"
    return (
        f"tau2 task {execution.task_id} ({execution.domain.value}). "
        f"Status: {status}. Reward: {execution.reward}. "
        f"Tools executed: {', '.join(action_names)}."
    )


def _agent_execution_summary(execution) -> str:
    step_actions = [step.action for step in execution.steps]
    status = "completed" if execution.task_success else "failed"
    return (
        f"tau2 task {execution.task_id} ({execution.domain.value}) via agent loop. "
        f"Status: {status}. Reward: {execution.reward}. "
        f"Agent actions: {', '.join(step_actions)}."
    )


def _expected_answer_for_execution(execution: Tau2EnvironmentExecution) -> str:
    return "yes" if execution.task_success else "no"


def build_fixture_from_executions(
    domain: Tau2Domain,
    tasks: list[Any],
    executions: list[Tau2EnvironmentExecution],
) -> SyntheticFixture:
    """Build a harness fixture from gold-replay environment executions."""
    ingest: list[IngestItem] = []
    queries: list[BenchmarkQuery] = []

    for task, execution in zip(tasks, executions, strict=True):
        item_id = f"{domain.value}-task-{task.id}"
        ingest.append(
            IngestItem(
                item_id=item_id,
                content=_execution_summary(execution),
                session_id=f"{domain.value}-run-{task.id}",
                metadata={
                    "domain": domain.value,
                    "tau2_task_id": str(task.id),
                    "fixture_source": REAL_FIXTURE_LABEL,
                    "harness_label": GOLD_REPLAY_HARNESS_LABEL,
                    "tau2_reward": execution.reward,
                    "tau2_task_success": execution.task_success,
                    "reason_for_call": _task_reason_for_call(task),
                    "environment_execution": execution.to_dict(),
                },
            )
        )
        queries.append(
            BenchmarkQuery(
                query_id=f"{domain.value}-q{task.id}",
                question=(
                    f"Did tau2 {domain.value} task {task.id} complete successfully "
                    f"in the real environment run?"
                ),
                expected_answer=_expected_answer_for_execution(execution),
                expected_memory_ids=(item_id,),
                task_success_criteria="completed" if execution.task_success else "failed",
                metadata={
                    "domain": domain.value,
                    "tau2_task_id": str(task.id),
                    "fixture_source": REAL_FIXTURE_LABEL,
                    "harness_label": GOLD_REPLAY_HARNESS_LABEL,
                    "tau2_reward": execution.reward,
                },
            )
        )

    return SyntheticFixture(
        family=BenchmarkFamily.TAU2_BENCH,
        ingest_items=tuple(ingest),
        queries=tuple(queries),
        consolidate_after_ingest=False,
    )


def load_real_domain_fixture(
    domain: Tau2Domain,
    *,
    task_split_name: str = DEFAULT_TASK_SPLIT,
    num_tasks: int = DEFAULT_NUM_TASKS,
    task_ids: list[str] | None = None,
    executions: list[Tau2EnvironmentExecution] | None = None,
) -> tuple[SyntheticFixture, list[Tau2EnvironmentExecution]]:
    """Load real tau2 tasks, optionally gold-replay environments for harness tests."""
    tasks = load_tau2_tasks(
        domain,
        task_split_name=task_split_name,
        num_tasks=num_tasks,
        task_ids=task_ids,
    )
    env_executions = executions or execute_domain_tasks(domain, tasks)
    fixture = build_fixture_from_executions(domain, tasks, env_executions)
    return fixture, env_executions


def load_real_domain_tasks(
    domain: Tau2Domain,
    *,
    task_split_name: str = DEFAULT_TASK_SPLIT,
    num_tasks: int = DEFAULT_NUM_TASKS,
    task_ids: list[str] | None = None,
) -> list[Any]:
    """Load real tau2 tasks without pre-running gold replay."""
    return load_tau2_tasks(
        domain,
        task_split_name=task_split_name,
        num_tasks=num_tasks,
        task_ids=task_ids,
    )


def fixture_provenance() -> dict[str, str]:
    data = provenance()
    data["fixture_source"] = REAL_FIXTURE_LABEL
    return data
