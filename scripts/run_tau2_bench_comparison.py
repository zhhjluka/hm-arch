#!/usr/bin/env python3
"""Run the tau2-bench agent-experience comparison (HM-76 / MEM-76).

Modes
-----

smoke
    Synthetic memory QA fixtures with the offline mock agent. Writes summary
    artifacts only; ``benchmark_table`` stays empty.

harness
    Real tau2 tasks driven by the labeled fake tau2 CLI
    (``tests/fixtures/fake_tau2_agent_cli.py``). Writes trajectories for CI;
    excluded from ``benchmark_table``.

real
    Production agent CLIs on PATH plus a CLI-backed or LLM tau2 user simulator.
    Unsupported or unauthenticated cells are recorded as ``unavailable`` /
    ``failed`` — never as completed benchmark metrics.

Credential-free CI / offline tests::

    python3 -m pytest tests/test_tau2_bench_comparison.py -v

    python3 scripts/run_tau2_bench_comparison.py --mode smoke --use-mock-agent

    python3 scripts/run_tau2_bench_comparison.py --mode harness \\
        --use-harness-agent \\
        --agent-executable tests/fixtures/fake_tau2_agent_cli.py \\
        --user-mode scripted \\
        --num-tasks 1

Production handoff (Codex / Claude Code review)::

    # 1. Install benchmark extras and sync the pinned tau2 fixture subset
    pip install -e '.[benchmark,dev]'
    python3 scripts/sync_tau2_bench_data.py

    # 2. REAL sweep — uses installed Codex/Claude CLIs for user simulation by default
    python3 scripts/run_tau2_bench_comparison.py \\
        --mode real \\
        --user-mode cli \\
        --num-tasks 3 \\
        --output-dir benchmark-results/tau2-comparison

    # Optional LLM-backed user simulator when a litellm route is available
    export TAU2_USER_LLM='openai/gpt-4o-mini'
    python3 scripts/run_tau2_bench_comparison.py \\
        --mode real \\
        --user-mode llm \\
        --user-llm \"$TAU2_USER_LLM\" \\
        --num-tasks 3 \\
        --output-dir benchmark-results/tau2-comparison

    # 3. Limited pilot (scripted user — excluded from benchmark_table)
    python3 scripts/run_tau2_bench_comparison.py \\
        --mode real \\
        --user-mode scripted \\
        --num-tasks 1 \\
        --output-dir benchmark-results/tau2-comparison-pilot

Codex will append verified REAL artifacts under ``benchmark-results/`` during
review. Hermes and OpenClaw cells remain explicit ``unavailable`` when their
CLIs are not installed.
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
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
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
        help="smoke = synthetic fixtures; harness = labeled agent-loop harness; real = production CLIs",
    )
    parser.add_argument(
        "--use-mock-agent",
        action="store_true",
        help="Use offline MockSyntheticAgentRunner for smoke mode",
    )
    parser.add_argument(
        "--use-harness-agent",
        action="store_true",
        help="Use labeled fake tau2 CLI that replays gold actions (harness only)",
    )
    parser.add_argument(
        "--agent-executable",
        type=Path,
        default=None,
        help="Override agent CLI executable (harness mode only)",
    )
    parser.add_argument("--agent-model", default=None)
    parser.add_argument("--agent-provider", default=None)
    parser.add_argument(
        "--user-mode",
        default="cli",
        choices=["llm", "scripted", "cli"],
    )
    parser.add_argument(
        "--user-llm",
        default=None,
        help="litellm model route for tau2 UserSimulator (required for real+llm)",
    )
    parser.add_argument(
        "--user-cli",
        default="auto",
        choices=["auto", "codex", "claude"],
        help="Installed CLI to simulate the tau2 user in real+cli mode",
    )
    parser.add_argument(
        "--user-cli-executable",
        type=Path,
        default=None,
        help="Override user CLI executable for real+cli mode",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--num-tasks", type=int, default=3)
    args = parser.parse_args()

    if args.mode == Tau2ComparisonMode.REAL.value:
        if args.use_mock_agent:
            parser.error("REAL mode cannot combine with --use-mock-agent")
        if args.use_harness_agent:
            parser.error("REAL mode cannot combine with --use-harness-agent")
        if args.agent_executable is not None:
            parser.error("REAL mode cannot combine with --agent-executable")
        if args.user_mode == "llm" and not args.user_llm:
            parser.error("REAL mode requires --user-llm when --user-mode=llm")

    config = Tau2ComparisonConfig(
        output_root=str(args.output_dir),
        top_k=args.top_k,
        mode=Tau2ComparisonMode(args.mode),
        use_mock_agent=args.use_mock_agent,
        use_harness_agent=args.use_harness_agent or args.mode == Tau2ComparisonMode.HARNESS.value,
        num_tasks=args.num_tasks,
        agent_executable=str(args.agent_executable) if args.agent_executable else None,
        agent_model=args.agent_model,
        agent_provider=args.agent_provider,
        user_mode=args.user_mode,
        user_llm=args.user_llm,
        user_cli=args.user_cli,
        user_cli_executable=(
            str(args.user_cli_executable) if args.user_cli_executable else None
        ),
    )
    report = run_tau2_comparison(config, output_root=args.output_dir)
    print(json.dumps(report.to_dict(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
