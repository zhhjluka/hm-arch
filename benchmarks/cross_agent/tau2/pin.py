"""Version-pinned tau2-bench reference (HM-76 / MEM-76)."""

from __future__ import annotations

import os
from pathlib import Path

TAU2_BENCH_REPO = "https://github.com/sierra-research/tau2-bench"
TAU2_BENCH_VERSION = "v1.0.0"
TAU2_BENCH_COMMIT = "17e07b1da2bbc0cadfddeea36412686e0604127b"
DEFAULT_TASK_SPLIT = "base"
DEFAULT_NUM_TASKS = 3

_REPO_ROOT = Path(__file__).resolve().parents[3]
BUNDLED_DATA_ROOT = _REPO_ROOT / "fixtures" / "tau2-bench" / TAU2_BENCH_VERSION / "data"

if BUNDLED_DATA_ROOT.is_dir() and not os.getenv("TAU2_DATA_DIR"):
    os.environ["TAU2_DATA_DIR"] = str(BUNDLED_DATA_ROOT)


def bundled_domain_dir(domain: str) -> Path:
    return BUNDLED_DATA_ROOT / "tau2" / "domains" / domain


def provenance() -> dict[str, str]:
    return {
        "tau2_bench_repo": TAU2_BENCH_REPO,
        "tau2_bench_version": TAU2_BENCH_VERSION,
        "tau2_bench_commit": TAU2_BENCH_COMMIT,
        "tau2_data_root": str(BUNDLED_DATA_ROOT),
        "task_split": DEFAULT_TASK_SPLIT,
    }
