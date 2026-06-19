"""HotpotQA matrix cell definitions for MEM-77."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..compatibility import compatibility_cell, lookup_matrix_cell
from ..types import AgentKind, MemoryBackendKind


class CellStatus(str, Enum):
    """Execution status for one matrix coordinate."""

    RUN = "run"
    PENDING = "pending"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class HotpotqaMatrixCell:
    """One agent × backend × top_k coordinate in the HotpotQA matrix."""

    agent: AgentKind
    backend: MemoryBackendKind
    top_k: int
    status: CellStatus
    rationale: str


_TOP_K_VALUES = (5, 20)
_ALL_BACKENDS = tuple(MemoryBackendKind)
_ALL_AGENTS = tuple(AgentKind)
_NON_OPENCLAW_AGENTS = (
    AgentKind.CODEX,
    AgentKind.CLAUDE_CODE,
    AgentKind.HERMES,
)


def _cell_status(agent: AgentKind, backend: MemoryBackendKind) -> tuple[CellStatus, str]:
    if agent is AgentKind.OPENCLAW:
        backend_cell = compatibility_cell(backend, agent)
        if backend_cell.supported and lookup_matrix_cell(agent, backend).implementation.value == "real":
            return (
                CellStatus.PENDING,
                "Deferred until OpenClaw integration is verified end-to-end (MEM-75).",
            )
        if not backend_cell.supported:
            return CellStatus.UNSUPPORTED, backend_cell.reason or "unsupported backend pairing"
        return (
            CellStatus.UNSUPPORTED,
            lookup_matrix_cell(agent, backend).rationale,
        )

    backend_cell = compatibility_cell(backend, agent)
    if not backend_cell.supported:
        return CellStatus.UNSUPPORTED, backend_cell.reason or "unsupported backend pairing"

    matrix_cell = lookup_matrix_cell(agent, backend)
    if matrix_cell.implementation.value == "real":
        return CellStatus.RUN, matrix_cell.rationale

    if matrix_cell.implementation.value == "mock_only":
        return (
            CellStatus.RUN,
            f"{matrix_cell.rationale} Executing with mock agent for offline retrieval comparison.",
        )

    return CellStatus.UNSUPPORTED, matrix_cell.rationale


def iter_hotpotqa_matrix_cells() -> tuple[HotpotqaMatrixCell, ...]:
    """Enumerate the full 5×4×2 HotpotQA matrix with execution status."""
    cells: list[HotpotqaMatrixCell] = []
    for agent in _ALL_AGENTS:
        for backend in _ALL_BACKENDS:
            status, rationale = _cell_status(agent, backend)
            for top_k in _TOP_K_VALUES:
                cells.append(
                    HotpotqaMatrixCell(
                        agent=agent,
                        backend=backend,
                        top_k=top_k,
                        status=status,
                        rationale=rationale,
                    )
                )
    return tuple(cells)


def runnable_non_openclaw_cells() -> tuple[HotpotqaMatrixCell, ...]:
    """Cells executed in MEM-77 (non-OpenClaw, supported coordinates)."""
    return tuple(
        cell
        for cell in iter_hotpotqa_matrix_cells()
        if cell.agent in _NON_OPENCLAW_AGENTS and cell.status is CellStatus.RUN
    )
