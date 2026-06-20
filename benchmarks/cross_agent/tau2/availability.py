"""tau2-bench import and data-directory helpers."""

from __future__ import annotations

import os
from functools import lru_cache
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from .pin import BUNDLED_DATA_ROOT, provenance


class Tau2UnavailableError(RuntimeError):
    """Raised when tau2-bench is required but not installed."""


def tau2_is_available() -> bool:
    return find_spec("tau2") is not None


def ensure_tau2_data_dir() -> Path:
    """Point TAU2_DATA_DIR at the bundled v1.0.0 fixtures when unset."""
    if not BUNDLED_DATA_ROOT.is_dir():
        raise Tau2UnavailableError(
            f"Bundled tau2 data missing at {BUNDLED_DATA_ROOT}. "
            "Run scripts/sync_tau2_bench_data.py."
        )
    os.environ.setdefault("TAU2_DATA_DIR", str(BUNDLED_DATA_ROOT))
    return BUNDLED_DATA_ROOT


@lru_cache(maxsize=1)
def tau2_runtime_info() -> dict[str, Any]:
    """Return installed tau2 revision metadata when available."""
    info = provenance()
    if not tau2_is_available():
        info["tau2_importable"] = False
        return info
    ensure_tau2_data_dir()
    from tau2.utils.utils import DATA_DIR, get_commit_hash

    info["tau2_importable"] = True
    info["tau2_runtime_commit"] = get_commit_hash()
    info["tau2_runtime_data_dir"] = str(DATA_DIR)
    return info


def require_tau2() -> None:
    if not tau2_is_available():
        raise Tau2UnavailableError(
            "tau2-bench is not installed. Install benchmark extras: "
            "pip install 'hm-arch[benchmark]' or see pyproject.toml."
        )
    ensure_tau2_data_dir()
