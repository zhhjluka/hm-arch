#!/usr/bin/env python3
"""Sync version-pinned tau2-bench retail/airline data into fixtures/."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from benchmarks.cross_agent.tau2.pin import (
    BUNDLED_DATA_ROOT,
    TAU2_BENCH_COMMIT,
    TAU2_BENCH_VERSION,
    bundled_domain_dir,
)

_ROOT = Path(__file__).resolve().parents[1]
_REPO = "https://github.com/sierra-research/tau2-bench.git"
_DOMAINS = ("retail", "airline")
_FILES = ("db.json", "tasks.json", "split_tasks.json", "policy.md")


def _clone_repo(target: Path, version: str) -> None:
    if target.exists():
        shutil.rmtree(target)
    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", version, _REPO, str(target)],
        check=True,
    )


def sync_data(*, version: str = TAU2_BENCH_VERSION, source: Path | None = None) -> Path:
    checkout = source
    temp_dir: Path | None = None
    if checkout is None:
        temp_dir = _ROOT / ".cache" / f"tau2-bench-{version}"
        _clone_repo(temp_dir, version)
        checkout = temp_dir

    for domain in _DOMAINS:
        src = checkout / "data" / "tau2" / "domains" / domain
        dst = bundled_domain_dir(domain)
        dst.mkdir(parents=True, exist_ok=True)
        for name in _FILES:
            shutil.copy2(src / name, dst / name)

    if temp_dir is not None:
        shutil.rmtree(temp_dir, ignore_errors=True)
    return BUNDLED_DATA_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=TAU2_BENCH_VERSION)
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Existing tau2-bench checkout (skips git clone)",
    )
    args = parser.parse_args()
    root = sync_data(version=args.version, source=args.source)
    print(f"Synced tau2-bench {args.version} ({TAU2_BENCH_COMMIT}) into {root}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(_ROOT))
    raise SystemExit(main())
