#!/usr/bin/env python3
"""Run the tau2-bench agent-experience comparison (HM-76 / MEM-76).

Usage::

    uv run python scripts/run_tau2_bench_comparison.py
    uv run python scripts/run_tau2_bench_comparison.py --output-dir benchmark-results/tau2-comparison

Offline tests::

    uv run pytest tests/test_tau2_bench_comparison.py -v
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from benchmarks.cross_agent.tau2 import (  # noqa: E402
    Tau2ComparisonConfig,
    run_tau2_comparison,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmark-results/tau2-comparison"),
        help="Root directory for comparison artifacts",
    )
    parser.add_argument(
        "--include-openclaw",
        action="store_true",
        help="Include OpenClaw cells (default: defer pending MEM-75)",
    )
    parser.add_argument(
        "--use-real-cli",
        action="store_true",
        help="Invoke production agent CLIs instead of the offline mock runner",
    )
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    config = Tau2ComparisonConfig(
        output_root=str(args.output_dir),
        top_k=args.top_k,
        use_mock_agent=not args.use_real_cli,
        include_openclaw=args.include_openclaw,
    )
    report = run_tau2_comparison(config, output_root=args.output_dir)
    print(json.dumps(report.to_dict(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
