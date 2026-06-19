"""Shared types for tau2-bench comparison artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..types import BenchmarkRunResult
from .config import Tau2Domain, Tau2MatrixCoordinate


@dataclass
class Tau2DomainRun:
    """One domain execution for a matrix cell."""

    domain: Tau2Domain
    result: BenchmarkRunResult | None = None
    trajectory_path: str | None = None
    error: str | None = None


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
                domain.value: {
                    "run_id": run.result.run_id if run.result else None,
                    "trajectory_path": run.trajectory_path,
                    "error": run.error,
                    "task_success_rate": (
                        run.result.aggregates.task_success_rate
                        if run.result
                        else None
                    ),
                }
                for domain, run in self.domain_results.items()
            },
        }
