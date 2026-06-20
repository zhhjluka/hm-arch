"""tau2-bench agent-experience comparison matrix configuration (HM-76 / MEM-76)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..compatibility import compatibility_cell, lookup_matrix_cell
from ..types import AgentKind, MemoryBackendKind
from .pin import DEFAULT_NUM_TASKS, DEFAULT_TASK_SPLIT, provenance

OPENCLAW_PENDING_ISSUE = "MEM-75"


class Tau2Domain(str, Enum):
    """tau2-bench evaluation domains."""

    RETAIL = "retail"
    AIRLINE = "airline"


class Tau2ComparisonMode(str, Enum):
    """Execution mode for the tau2 comparison sweep."""

    SMOKE = "smoke"
    HARNESS = "harness"
    REAL = "real"


DOMAIN_SEEDS: dict[Tau2Domain, int] = {
    Tau2Domain.RETAIL: 0,
    Tau2Domain.AIRLINE: 1,
}

COMPARISON_BACKENDS: tuple[MemoryBackendKind, ...] = (
    MemoryBackendKind.NO_MEMORY,
    MemoryBackendKind.NATIVE_MEMORY,
    MemoryBackendKind.MEM0,
    MemoryBackendKind.OPENVIKING,
    MemoryBackendKind.HM_ARCH,
)

COMPARISON_AGENTS: tuple[AgentKind, ...] = (
    AgentKind.CODEX,
    AgentKind.CLAUDE_CODE,
    AgentKind.HERMES,
    AgentKind.OPENCLAW,
)


@dataclass(frozen=True)
class Tau2MatrixCoordinate:
    """One agent × memory backend cell in the tau2 comparison matrix."""

    agent: AgentKind
    backend: MemoryBackendKind

    @property
    def key(self) -> str:
        return f"{self.agent.value}|{self.backend.value}"


@dataclass(frozen=True)
class Tau2ComparisonConfig:
    """Runtime options for the tau2-bench comparison sweep."""

    output_root: str = "benchmark-results/tau2-comparison"
    top_k: int = 5
    mode: Tau2ComparisonMode = Tau2ComparisonMode.REAL
    use_mock_agent: bool = False
    use_harness_agent: bool = False
    include_openclaw: bool = False
    domains: tuple[Tau2Domain, ...] = (Tau2Domain.RETAIL, Tau2Domain.AIRLINE)
    task_split_name: str = DEFAULT_TASK_SPLIT
    num_tasks: int = DEFAULT_NUM_TASKS
    agent_executable: str | None = None
    agent_model: str | None = None
    agent_provider: str | None = None
    user_mode: str = "llm"
    user_llm: str | None = None
    consolidate_memory: bool = True

    def user_simulator_label(self) -> str | None:
        """Label how the tau2 user simulator is configured in REAL mode."""
        if self.mode is not Tau2ComparisonMode.REAL:
            return None
        if self.user_mode == "scripted":
            return "scripted_user_pilot"
        if self.user_llm:
            return "llm_user_simulator"
        return None

    def validate_real_mode(self) -> tuple[str, str] | None:
        """Return (status, rationale) when REAL mode configuration is invalid."""
        if self.mode is not Tau2ComparisonMode.REAL:
            return None
        if self.use_mock_agent:
            return "failed", "REAL mode cannot use --use-mock-agent"
        if self.use_harness_agent:
            return "failed", "REAL mode cannot use harness gold-action replay"
        if self.agent_executable:
            return (
                "failed",
                "REAL mode must resolve production agent CLIs; remove --agent-executable",
            )
        if self.user_mode == "llm" and not self.user_llm:
            return (
                "failed",
                "REAL mode requires --user-llm when --user-mode=llm "
                "(or pass --user-mode scripted for a labeled limited pilot)",
            )
        if self.user_mode not in {"llm", "scripted"}:
            return "failed", f"Unsupported user_mode: {self.user_mode}"
        return None

    def provenance(self) -> dict[str, str | int | bool | None]:
        data: dict[str, str | int | bool | None] = {
            **provenance(),
            "mode": self.mode.value,
            "use_mock_agent": self.use_mock_agent,
            "use_harness_agent": self.use_harness_agent,
            "task_split_name": self.task_split_name,
            "num_tasks": self.num_tasks,
            "agent_executable": self.agent_executable,
            "agent_model": self.agent_model,
            "agent_provider": self.agent_provider,
            "user_mode": self.user_mode,
            "user_llm": self.user_llm,
            "user_simulator_label": self.user_simulator_label(),
            "consolidate_memory": self.consolidate_memory,
        }
        return data


def tau2_matrix_coordinates() -> tuple[Tau2MatrixCoordinate, ...]:
    """Return the full agent × backend matrix for tau2-bench."""
    return tuple(
        Tau2MatrixCoordinate(agent=agent, backend=backend)
        for agent in COMPARISON_AGENTS
        for backend in COMPARISON_BACKENDS
    )


def cell_support_rationale(agent: AgentKind, backend: MemoryBackendKind) -> tuple[bool, str]:
    """Return backend-level support and rationale for a matrix cell."""
    cell = compatibility_cell(backend, agent)
    if not cell.supported:
        return False, cell.reason or "unsupported"
    matrix = lookup_matrix_cell(agent, backend)
    return True, matrix.rationale
