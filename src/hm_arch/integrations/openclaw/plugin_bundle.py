"""Copy bundled OpenClaw plugin runtime files into an extension directory."""

from __future__ import annotations

import shutil
from pathlib import Path

from .config import resolve_bundled_openclaw_plugin_dir


def install_openclaw_plugin_runtime(plugin_dir: Path) -> bool:
    """Install the HM-Arch OpenClaw plugin runtime into *plugin_dir*.

    Returns ``True`` when a loadable runtime was installed, ``False`` when only
    a management stub could be written.
    """
    plugin_dir.mkdir(parents=True, exist_ok=True)
    bundled = resolve_bundled_openclaw_plugin_dir()
    if bundled is not None:
        _copy_bundled_runtime(bundled, plugin_dir)
        return True
    _write_runtime_stub(plugin_dir)
    return False


def _copy_bundled_runtime(source: Path, destination: Path) -> None:
    manifest = source / "openclaw.plugin.json"
    if manifest.exists():
        shutil.copy2(manifest, destination / "openclaw.plugin.json")

    package_json = source / "package.json"
    if package_json.exists():
        shutil.copy2(package_json, destination / "package.json")

    dist_dir = source / "dist"
    if dist_dir.is_dir():
        target_dist = destination / "dist"
        if target_dist.exists():
            shutil.rmtree(target_dist)
        shutil.copytree(dist_dir, target_dist)
        (destination / "index.mjs").write_text(
            'export { register } from "./dist/index.js";\n',
            encoding="utf-8",
        )
        return

    entrypoint = source / "index.mjs"
    if entrypoint.exists():
        shutil.copy2(entrypoint, destination / "index.mjs")


def _write_runtime_stub(plugin_dir: Path) -> None:
    marker = "HM-Arch OpenClaw plugin runtime is not installed"
    (plugin_dir / "index.mjs").write_text(
        "// HM-Arch OpenClaw memory plugin entrypoint.\n"
        "// Full runtime is provided by @hm-arch/openclaw-plugin when published.\n"
        "export async function register() {\n"
        f"  throw new Error('{marker}. "
        "Install @hm-arch/openclaw-plugin or run hm-arch install openclaw.');\n"
        "}\n",
        encoding="utf-8",
    )
