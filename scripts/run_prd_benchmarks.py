#!/usr/bin/env python3
"""Run HM-Arch PRD scale/performance benchmarks and print a JSON report.

Usage::

    uv run python scripts/run_prd_benchmarks.py
    uv run python scripts/run_prd_benchmarks.py --output /tmp/prd_benchmark.json

Equivalent pytest entry point::

    uv run pytest tests/prd_benchmarks -m benchmark -v

Default ``uv run pytest`` excludes ``benchmark``-marked tests (see ``pyproject.toml``).
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

# Repo root on sys.path when invoked as a script.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from benchmarks.harness import run_prd_benchmark_suite  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON report to this path (default: stdout only)",
    )
    parser.add_argument(
        "--tmp-dir",
        type=Path,
        default=None,
        help="Use this directory for benchmark databases (default: temp dir)",
    )
    args = parser.parse_args()

    tmp_ctx: tempfile.TemporaryDirectory[str] | None = None
    if args.tmp_dir is not None:
        tmp_root = args.tmp_dir
        tmp_root.mkdir(parents=True, exist_ok=True)
    else:
        tmp_ctx = tempfile.TemporaryDirectory(prefix="hm_arch_prd_bench_")
        tmp_root = Path(tmp_ctx.name)

    report = run_prd_benchmark_suite(tmp_root)
    payload = report.to_json()
    if args.output is not None:
        args.output.write_text(payload, encoding="utf-8")
        print(f"Wrote benchmark report to {args.output}")
    else:
        print(payload)

    failed = [name for name, ok in report.assertions.items() if not ok]
    if failed:
        print("\nFAILED assertions:", ", ".join(failed), file=sys.stderr)
        return 1
    print("\nAll PRD benchmark assertions passed.", file=sys.stderr)
    if tmp_ctx is not None:
        tmp_ctx.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
