#!/usr/bin/env python3
"""Run the LoCoMo cross-agent memory comparison matrix (MEM-78 / HM-75).

Usage::

    uv run python scripts/run_locomo_matrix.py
    uv run python scripts/run_locomo_matrix.py --dataset-id locomo10-sample
    uv run python scripts/run_locomo_matrix.py --max-conversations 2

Offline tests::

    uv run pytest tests/test_locomo_matrix.py -v
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from benchmarks.cross_agent.locomo_matrix import run_locomo_matrix  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmark-results/locomo-matrix"),
        help="Directory for per-run artifacts and matrix_summary.json",
    )
    parser.add_argument(
        "--dataset-id",
        type=str,
        default="locomo10",
        help="Versioned LoCoMo dataset id from manifest.json",
    )
    parser.add_argument(
        "--dataset-version",
        type=str,
        default=None,
        help="Expected dataset version pin (defaults to manifest version)",
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--max-conversations",
        type=int,
        default=None,
        help="Limit conversations ingested from the dataset (default: all)",
    )
    parser.add_argument(
        "--include-openclaw",
        action="store_true",
        help="Attempt OpenClaw cells (default: mark pending for MEM-75)",
    )
    parser.add_argument(
        "--use-real-cli",
        action="store_true",
        help="Invoke production agent CLIs instead of the offline mock runner",
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = run_locomo_matrix(
        output_root=args.output_dir,
        dataset_id=args.dataset_id,
        dataset_version=args.dataset_version,
        seed=args.seed,
        top_k=args.top_k,
        use_mock_agent=not args.use_real_cli,
        include_openclaw=args.include_openclaw,
        max_conversations=args.max_conversations,
    )
    summary_path = args.output_dir / "matrix_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, default=str))
    print(f"\nWrote matrix summary to {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
