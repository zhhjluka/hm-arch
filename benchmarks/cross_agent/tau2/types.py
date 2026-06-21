"""Shared types for tau2-bench comparison artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..types import BenchmarkRunResult
from .agent_loop import Tau2AgentTaskExecution
from .config import Tau2Domain, Tau2MatrixCoordinate
from .environment_runner import Tau2EnvironmentExecution


@dataclass
class Tau2DomainMetrics:
    """Aggregated metrics for one domain agent-loop run."""

    task_count: int = 0
    task_success_rate: float | None = None
    mean_task_time_ms: float | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_failure_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_count": self.task_count,
            "task_success_rate": self.task_success_rate,
            "mean_task_time_ms": self.mean_task_time_ms,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_failure_count": self.total_failure_count,
        }


def aggregate_agent_executions(
    executions: list[Tau2AgentTaskExecution],
) -> Tau2DomainMetrics:
    if not executions:
        return Tau2DomainMetrics()
    successes = sum(1 for item in executions if item.task_success)
    durations = [item.duration_ms for item in executions]
    input_tokens = sum(
        step.input_tokens for item in executions for step in item.steps
    )
    output_tokens = sum(
        step.output_tokens for item in executions for step in item.steps
    )
    failures = sum(1 for item in executions if item.error)
    failures += sum(
        1 for item in executions for step in item.steps if step.error
    )
    return Tau2DomainMetrics(
        task_count=len(executions),
        task_success_rate=successes / len(executions),
        mean_task_time_ms=sum(durations) / len(durations),
        total_input_tokens=input_tokens,
        total_output_tokens=output_tokens,
        total_failure_count=failures,
    )


@dataclass
class Tau2DomainRun:
    """One domain execution for a matrix cell."""

    domain: Tau2Domain
    result: BenchmarkRunResult | None = None
    trajectory_path: str | None = None
    error: str | None = None
    env_executions: list[Tau2EnvironmentExecution] = field(default_factory=list)
    agent_executions: list[Tau2AgentTaskExecution] = field(default_factory=list)
    metrics: Tau2DomainMetrics | None = None
    run_id: str | None = None

    def to_status_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id or (self.result.run_id if self.result else None),
            "trajectory_path": self.trajectory_path,
            "error": self.error,
            "task_success_rate": (
                self.metrics.task_success_rate
                if self.metrics
                else (
                    self.result.aggregates.task_success_rate
                    if self.result
                    else None
                )
            ),
            "environment_execution_count": len(self.env_executions),
            "agent_execution_count": len(self.agent_executions),
            "agent_invocation_mode": (
                self.agent_executions[0].agent_invocation_mode
                if self.agent_executions
                else None
            ),
        }


@dataclass
class Tau2CellResult:
    """Aggregated retail + airline runs for one agent × backend cell."""

    coordinate: Tau2MatrixCoordinate
    status: str
    rationale: str | None = None
    domain_results: dict[Tau2Domain, Tau2DomainRun] = field(default_factory=dict)

    def to_status_dict(self) -> dict[str, Any]:
        return {
            "agent": self.coordinate.agent.value,
            "backend": self.coordinate.backend.value,
            "status": self.status,
            "rationale": self.rationale,
            "domains": {
                domain.value: run.to_status_dict()
                for domain, run in self.domain_results.items()
            },
        }
