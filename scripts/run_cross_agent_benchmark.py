#!/usr/bin/env python3
"""Run cross-agent memory benchmarks (HM-71 / MEM-68).

Usage::

    uv run python scripts/run_cross_agent_benchmark.py
    uv run python scripts/run_cross_agent_benchmark.py --family locomo --backend hm_arch
    uv run python scripts/run_cross_agent_benchmark.py --matrix

Offline tests::

    uv run pytest tests/test_cross_agent_benchmark.py -v
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from benchmarks.cross_agent import (  # noqa: E402
    AgentKind,
    BenchmarkFamily,
    BenchmarkRunConfig,
    MemoryBackendKind,
    run_cross_agent_benchmark,
)
from benchmarks.cross_agent.runner import run_synthetic_matrix  # noqa: E402


def _parse_family(value: str) -> BenchmarkFamily:
    return BenchmarkFamily(value.lower())


def _parse_agent(value: str) -> AgentKind:
    return AgentKind(value.lower())


def _parse_backend(value: str) -> MemoryBackendKind:
    return MemoryBackendKind(value.lower())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmark-results"),
        help="Directory for JSONL/CSV/summary artifacts",
    )
    parser.add_argument("--family", type=_parse_family, default=BenchmarkFamily.LOCOMO)
    parser.add_argument("--agent", type=_parse_agent, default=AgentKind.CODEX)
    parser.add_argument("--backend", type=_parse_backend, default=MemoryBackendKind.HM_ARCH)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument(
        "--matrix",
        action="store_true",
        help="Run synthetic fixtures for all benchmark families",
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.matrix:
        results = run_synthetic_matrix(output_root=args.output_dir)
        print(json.dumps([r.to_dict() for r in results], indent=2, default=str))
        return 0

    config = BenchmarkRunConfig(
        family=args.family,
        agent=args.agent,
        backend=args.backend,
        seed=args.seed,
        top_k=args.top_k,
        resume=not args.no_resume,
    )
    result = run_cross_agent_benchmark(config, output_root=args.output_dir)
    print(json.dumps(result.to_dict(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
