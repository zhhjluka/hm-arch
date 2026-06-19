#!/usr/bin/env python3
"""Run the HotpotQA retrieval and efficiency matrix (MEM-77).

Usage::

    uv run python scripts/run_hotpotqa_matrix.py
    uv run python scripts/run_hotpotqa_matrix.py --output-dir benchmark-results/hotpotqa
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from benchmarks.cross_agent.fixtures.hotpotqa import (  # noqa: E402
    HOTPOTQA_SUBSET_VERSION,
    compute_subset_hash,
    load_hotpotqa_config,
)
from benchmarks.cross_agent.hotpotqa import (  # noqa: E402
    expected_runnable_cell_count,
    iter_hotpotqa_matrix_cells,
    run_hotpotqa_matrix,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmark-results/hotpotqa"),
        help="Directory for per-run artifacts and matrix_summary.json",
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--use-real-cli",
        action="store_true",
        help="Invoke production agent CLIs instead of the offline mock runner",
    )
    parser.add_argument(
        "--include-openclaw",
        action="store_true",
        help="Attempt OpenClaw cells (default: mark as pending per MEM-75)",
    )
    args = parser.parse_args()

    config = load_hotpotqa_config()
    print(
        json.dumps(
            {
                "subset_version": HOTPOTQA_SUBSET_VERSION,
                "subset_hash": compute_subset_hash(),
                "seed": config["seed"],
                "query_count": config["query_count"],
                "document_count": config["document_count"],
                "matrix_cells": len(list(iter_hotpotqa_matrix_cells())),
                "runnable_non_openclaw_cells": expected_runnable_cell_count(),
            },
            indent=2,
        )
    )

    summary = run_hotpotqa_matrix(
        output_root=args.output_dir,
        seed=args.seed,
        use_mock_agent=not args.use_real_cli,
        include_openclaw=args.include_openclaw,
    )
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
