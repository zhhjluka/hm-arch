"""HotpotQA retrieval and efficiency comparison (MEM-77)."""

from .cells import CellStatus, HotpotqaMatrixCell, iter_hotpotqa_matrix_cells, runnable_cells, runnable_non_openclaw_cells
from .matrix import HotpotqaMatrixRunOutcome, expected_runnable_cell_count, run_hotpotqa_matrix
from .manifest import ResolvedExecutable, build_run_manifest, collect_agent_executables, write_run_manifest
from .summary import HotpotqaCellSummary, build_matrix_summary, summarize_cell, write_matrix_summary

__all__ = [
  "CellStatus",
  "HotpotqaCellSummary",
  "HotpotqaMatrixCell",
  "HotpotqaMatrixRunOutcome",
  "ResolvedExecutable",
  "build_matrix_summary",
  "build_run_manifest",
  "collect_agent_executables",
  "expected_runnable_cell_count",
  "iter_hotpotqa_matrix_cells",
  "runnable_cells",
  "runnable_non_openclaw_cells",
  "run_hotpotqa_matrix",
  "summarize_cell",
  "write_matrix_summary",
  "write_run_manifest",
]
