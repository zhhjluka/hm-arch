"""tau2-bench import and data-directory helpers."""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from importlib.util import find_spec
from pathlib import Path
from types import ModuleType
from typing import Any

from .pin import BUNDLED_DATA_ROOT, provenance


class Tau2UnavailableError(RuntimeError):
    """Raised when tau2-bench is required but not installed."""


def _stub_tau2_optional_deps() -> None:
    """Stub optional native deps so tau2 imports work in CI without voice extras."""
    if "pyaudio" not in sys.modules:
        sys.modules["pyaudio"] = ModuleType("pyaudio")
    if "elevenlabs" not in sys.modules:
        elevenlabs = ModuleType("elevenlabs")
        elevenlabs.ElevenLabs = object  # type: ignore[attr-defined]
        sys.modules["elevenlabs"] = elevenlabs


def tau2_is_available() -> bool:
    if find_spec("tau2") is None:
        return False
    try:
        _stub_tau2_optional_deps()
        import tau2  # noqa: F401
    except Exception:
        return False
    return True


def ensure_tau2_data_dir() -> Path:
    """Point TAU2_DATA_DIR at the bundled v1.0.0 fixtures when unset."""
    if not BUNDLED_DATA_ROOT.is_dir():
        raise Tau2UnavailableError(
            f"Bundled tau2 data missing at {BUNDLED_DATA_ROOT}. "
            "Run scripts/sync_tau2_bench_data.py."
        )
    os.environ["TAU2_DATA_DIR"] = str(BUNDLED_DATA_ROOT)
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
    if find_spec("tau2") is None:
        raise Tau2UnavailableError(
            "tau2-bench is not installed. Install benchmark extras: "
            "pip install 'hm-arch[benchmark]' or see pyproject.toml."
        )
    _stub_tau2_optional_deps()
    try:
        import tau2  # noqa: F401
    except Exception as exc:
        raise Tau2UnavailableError(
            "tau2-bench is installed but failed to import. "
            "Install benchmark extras: pip install 'hm-arch[benchmark]'."
        ) from exc
    ensure_tau2_data_dir()
