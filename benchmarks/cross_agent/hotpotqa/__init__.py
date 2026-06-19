"""HotpotQA retrieval and efficiency comparison (MEM-77)."""

from .cells import CellStatus, HotpotqaMatrixCell, iter_hotpotqa_matrix_cells, runnable_non_openclaw_cells
from .matrix import HotpotqaMatrixRunOutcome, expected_runnable_cell_count, run_hotpotqa_matrix
from .summary import HotpotqaCellSummary, build_matrix_summary, summarize_cell, write_matrix_summary

__all__ = [
  "CellStatus",
  "HotpotqaCellSummary",
  "HotpotqaMatrixCell",
  "HotpotqaMatrixRunOutcome",
  "build_matrix_summary",
  "expected_runnable_cell_count",
  "iter_hotpotqa_matrix_cells",
  "runnable_non_openclaw_cells",
  "run_hotpotqa_matrix",
  "summarize_cell",
  "write_matrix_summary",
]
