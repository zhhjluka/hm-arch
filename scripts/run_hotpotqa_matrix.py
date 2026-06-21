#!/usr/bin/env python3
"""Run the HotpotQA retrieval and efficiency matrix (MEM-77).

Usage::

    # Production comparison matrix (requires host agent CLIs on PATH)
    uv run python scripts/run_hotpotqa_matrix.py --use-real-cli

    # Offline mock-synthetic smoke (harness lifecycle only; separate output dir)
    uv run python scripts/run_hotpotqa_matrix.py --mock-smoke

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
        default=None,
        help="Directory for per-run artifacts and matrix_summary.json",
    )
    parser.add_argument("--seed", type=int, default=0)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--use-real-cli",
        action="store_true",
        help="Invoke production agent CLIs (default when neither mode flag is set)",
    )
    mode.add_argument(
        "--mock-smoke",
        action="store_true",
        help="Run offline mock-synthetic smoke into benchmark-results/hotpotqa-smoke",
    )
    parser.add_argument(
        "--allow-test-double",
        action="store_true",
        help="Allow fake_agent_cli test doubles (tests/CI only; not comparison conclusions)",
    )
    parser.add_argument(
        "--agent-executable",
        type=str,
        default=None,
        help="Override agent CLI executable for all agents (tests/CI)",
    )
    args = parser.parse_args()

    use_mock_agent = args.mock_smoke
    execution_mode = "mock_smoke" if use_mock_agent else "comparison"
    output_dir = args.output_dir or (
        Path("benchmark-results/hotpotqa-smoke")
        if use_mock_agent
        else Path("benchmark-results/hotpotqa")
    )
    command = " ".join(sys.argv)

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
                "runnable_cells": expected_runnable_cell_count(),
                "execution_mode": execution_mode,
                "use_mock_agent": use_mock_agent,
                "output_dir": str(output_dir),
            },
            indent=2,
        )
    )

    summary = run_hotpotqa_matrix(
        output_root=output_dir,
        seed=args.seed,
        use_mock_agent=use_mock_agent,
        agent_executable=args.agent_executable,
        allow_test_double=args.allow_test_double,
        execution_mode=execution_mode,
        command=command,
    )
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
