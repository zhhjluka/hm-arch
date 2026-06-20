#!/usr/bin/env python3
"""Run the tau2-bench agent-experience comparison (HM-76 / MEM-76).

Usage::

    # Real tau2-bench tasks + CLI boundary (default)
    uv run python scripts/run_tau2_bench_comparison.py

    # Labeled synthetic smoke evidence only
    uv run python scripts/run_tau2_bench_comparison.py --mode smoke --use-mock-agent

    # Real tau2 with explicit CLI executable
    uv run python scripts/run_tau2_bench_comparison.py \\
        --agent-executable tests/fixtures/fake_agent_cli.py

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
    Tau2ComparisonMode,
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
        "--mode",
        choices=[mode.value for mode in Tau2ComparisonMode],
        default=Tau2ComparisonMode.REAL.value,
        help="smoke = labeled synthetic fixtures; real = version-pinned tau2-bench",
    )
    parser.add_argument(
        "--include-openclaw",
        action="store_true",
        help="Include OpenClaw cells (default: defer pending MEM-75)",
    )
    parser.add_argument(
        "--use-mock-agent",
        action="store_true",
        help="Use offline MockSyntheticAgentRunner instead of CLI runners",
    )
    parser.add_argument(
        "--agent-executable",
        type=Path,
        default=None,
        help="Override agent CLI executable for supported cells",
    )
    parser.add_argument("--agent-model", default=None)
    parser.add_argument("--agent-provider", default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--num-tasks", type=int, default=3)
    args = parser.parse_args()

    config = Tau2ComparisonConfig(
        output_root=str(args.output_dir),
        top_k=args.top_k,
        mode=Tau2ComparisonMode(args.mode),
        use_mock_agent=args.use_mock_agent,
        include_openclaw=args.include_openclaw,
        num_tasks=args.num_tasks,
        agent_executable=str(args.agent_executable) if args.agent_executable else None,
        agent_model=args.agent_model,
        agent_provider=args.agent_provider,
    )
    report = run_tau2_comparison(config, output_root=args.output_dir)
    print(json.dumps(report.to_dict(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
