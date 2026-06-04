"""Minimal ``config.toml`` helpers for Codex hook feature flags."""

from __future__ import annotations

import re
from pathlib import Path

_FEATURES_SECTION_RE = re.compile(r"(?ms)^\s*\[features\]\s*$")
_HOOKS_TRUE_RE = re.compile(
    r"(?m)^\s*(?:hooks|codex_hooks)\s*=\s*true\s*$",
)


def hooks_feature_enabled(text: str) -> bool:
    """Return True when Codex hooks are already enabled in *text*."""
    return bool(_HOOKS_TRUE_RE.search(text))


def ensure_hooks_enabled(config_path: Path) -> bool:
    """Ensure ``[features].hooks = true`` without mutating unrelated settings.

    Returns True when the file was changed.
    """
    if config_path.exists():
        original = config_path.read_text(encoding="utf-8")
    else:
        original = ""

    if hooks_feature_enabled(original):
        return False

    if not original.strip():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            "[features]\nhooks = true\n",
            encoding="utf-8",
        )
        return True

    if _FEATURES_SECTION_RE.search(original):
        updated = _FEATURES_SECTION_RE.sub(
            "[features]\nhooks = true",
            original,
            count=1,
        )
    else:
        suffix = "" if original.endswith("\n") else "\n"
        updated = f"{original}{suffix}\n[features]\nhooks = true\n"

    if updated != original:
        config_path.write_text(updated, encoding="utf-8")
        return True
    return False
