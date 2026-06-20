#!/usr/bin/env python3
"""Run the LoCoMo cross-agent memory comparison matrix (MEM-78 / HM-75).

Usage::

    # Offline mock smoke (default) — not production cross-agent comparison
    uv run python scripts/run_locomo_matrix.py --dataset-id locomo10-sample

    # Real supported agent CLI runs (Hermes/Claude/Codex no_memory + hm_arch)
    uv run python scripts/run_locomo_matrix.py \\
      --runner-mode real --dataset-id locomo10-sample --max-conversations 1

    # With a test double executable for CI
    uv run python scripts/run_locomo_matrix.py \\
      --runner-mode real --agent-executable tests/fixtures/fake_agent_cli.py \\
      --dataset-id locomo10-sample --max-conversations 1

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

from benchmarks.cross_agent.locomo_matrix import (  # noqa: E402
    MatrixRunnerMode,
    run_locomo_matrix,
)


def _parse_runner_mode(value: str) -> MatrixRunnerMode:
    normalized = value.strip().lower().replace("-", "_")
    if normalized in {"mock", "offline"}:
        return MatrixRunnerMode.MOCK
    if normalized in {"real", "cli"}:
        return MatrixRunnerMode.REAL
    raise argparse.ArgumentTypeError(
        f"Unknown runner mode {value!r}; expected mock or real"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmark-results/locomo-matrix"),
        help="Directory for per-run artifacts and matrix summary JSON",
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
        "--runner-mode",
        type=_parse_runner_mode,
        default=MatrixRunnerMode.MOCK,
        help="mock = offline smoke (default); real = production agent CLI runs",
    )
    parser.add_argument(
        "--use-real-cli",
        action="store_true",
        help="Deprecated alias for --runner-mode real",
    )
    parser.add_argument(
        "--agent-executable",
        type=str,
        default=None,
        help="Override agent CLI executable for all real-mode cells",
    )
    parser.add_argument(
        "--agent-timeout-s",
        type=float,
        default=120.0,
        help="Agent CLI timeout in seconds",
    )
    args = parser.parse_args()

    runner_mode = MatrixRunnerMode.REAL if args.use_real_cli else args.runner_mode
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = run_locomo_matrix(
        output_root=args.output_dir,
        dataset_id=args.dataset_id,
        dataset_version=args.dataset_version,
        seed=args.seed,
        top_k=args.top_k,
        runner_mode=runner_mode,
        include_openclaw=args.include_openclaw,
        max_conversations=args.max_conversations,
        agent_executable=args.agent_executable,
        agent_timeout_s=args.agent_timeout_s,
    )
    summary_name = (
        "matrix_summary_mock.json"
        if runner_mode is MatrixRunnerMode.MOCK
        else "matrix_summary_real.json"
    )
    summary_path = args.output_dir / summary_name
    summary_path.write_text(
        json.dumps(summary, indent=2, default=str),
        encoding="utf-8",
    )
    # Keep a stable pointer for tooling that expects matrix_summary.json.
    pointer_path = args.output_dir / "matrix_summary.json"
    pointer_payload = {
        "active_report": summary_name,
        "report_type": summary["report_type"],
        "runner_mode": summary["runner_mode"],
        "path": str(summary_path),
    }
    pointer_path.write_text(
        json.dumps(pointer_payload, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, default=str))
    print(f"\nWrote {runner_mode.value} matrix summary to {summary_path}")
    print(f"Wrote summary pointer to {pointer_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
