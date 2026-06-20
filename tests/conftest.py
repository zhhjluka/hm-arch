"""Shared pytest hooks for offline benchmark tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import ModuleType

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TAU2_DATA_ROOT = _REPO_ROOT / "fixtures" / "tau2-bench" / "v1.0.0" / "data"
if _TAU2_DATA_ROOT.is_dir():
    os.environ["TAU2_DATA_DIR"] = str(_TAU2_DATA_ROOT)


def _install_optional_dep_stubs() -> None:
    if "pyaudio" not in sys.modules:
        sys.modules["pyaudio"] = ModuleType("pyaudio")
    if "elevenlabs" not in sys.modules:
        elevenlabs = ModuleType("elevenlabs")
        elevenlabs.ElevenLabs = object  # type: ignore[attr-defined]
        sys.modules["elevenlabs"] = elevenlabs


_install_optional_dep_stubs()
