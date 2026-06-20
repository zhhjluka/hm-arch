"""Resolve the canonical HM-Arch OpenClaw plugin package on disk."""

from __future__ import annotations

import json
import shutil
import sys
from importlib import resources
from pathlib import Path

from hm_arch._version import __version__

_PLUGIN_PACKAGE_DIRNAME = "openclaw-plugin"
_BUNDLED_PLUGIN_PACKAGE = "hm_arch.integrations.openclaw.bundled_plugin"
_PLUGIN_PAYLOAD_FILES = (
    "package.json",
    "openclaw.plugin.json",
    "dist/index.js",
)


def resolve_bundled_plugin_source() -> Path:
    """Return the canonical @hm-arch/openclaw-plugin package directory."""
    for candidate in _plugin_source_candidates():
        if _plugin_package_ready(candidate):
            return candidate

    raise FileNotFoundError(
        "HM-Arch OpenClaw plugin package is missing from the installation"
    )


def _plugin_source_candidates() -> list[Path]:
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / _PLUGIN_PACKAGE_DIRNAME)

    module_dir = Path(__file__).resolve().parent
    candidates.append(module_dir.parents[3] / "packages" / _PLUGIN_PACKAGE_DIRNAME)

    wheel_source = _wheel_bundled_plugin_source()
    if wheel_source is not None:
        candidates.append(wheel_source)

    return candidates


def _wheel_bundled_plugin_source() -> Path | None:
    """Return the wheel-bundled plugin directory when installed from PyPI."""
    try:
        root = resources.files(_BUNDLED_PLUGIN_PACKAGE)
    except (ModuleNotFoundError, TypeError):
        return None

    candidate = Path(str(root))
    if _plugin_package_ready(candidate):
        return candidate
    return None


def _plugin_package_ready(path: Path) -> bool:
    if not path.is_dir():
        return False
    return all((path / relative).is_file() for relative in _PLUGIN_PAYLOAD_FILES)


def read_plugin_package_version(source: Path) -> str | None:
    """Return the semver from the plugin package.json when present."""
    package_json = source / "package.json"
    if not package_json.is_file():
        return None
    data = json.loads(package_json.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    version = data.get("version")
    return version if isinstance(version, str) and version.strip() else None


def verify_plugin_package_version(source: Path) -> None:
    """Fail clearly when the bundled plugin version does not match hm-arch."""
    bundled_version = read_plugin_package_version(source)
    if bundled_version is None:
        return
    if bundled_version != __version__:
        raise ValueError(
            f"OpenClaw plugin version mismatch: bundled {bundled_version} "
            f"!= hm-arch {__version__}"
        )


def plugin_payload_matches(source: Path, destination: Path) -> bool:
    """Return True when the installed plugin tree matches the bundled package."""
    if not destination.is_dir():
        return False
    for relative in _PLUGIN_PAYLOAD_FILES:
        src = source / relative
        dst = destination / relative
        if not src.is_file() or not dst.is_file():
            return False
        if src.read_bytes() != dst.read_bytes():
            return False
    return True


def install_plugin_package(source: Path, destination: Path) -> bool:
    """Copy the canonical plugin package into an OpenClaw extensions directory."""
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("node_modules", ".git"),
    )
    return True
