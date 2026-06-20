"""Wheel install smoke tests for OpenClaw integration management."""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from hm_arch.integrations.openclaw.config import HM_ARCH_PLUGIN_ID

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PLUGIN_PAYLOAD_FILES = (
    "package.json",
    "openclaw.plugin.json",
    "dist/index.js",
)


def _build_wheel(destination: Path) -> Path:
    build = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--outdir",
            str(destination),
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if build.returncode != 0:
        raise RuntimeError(
            "Failed to build hm-arch wheel:\n"
            f"stdout:\n{build.stdout}\nstderr:\n{build.stderr}"
        )

    wheels = sorted(destination.glob("hm_arch-*.whl"))
    if not wheels:
        raise FileNotFoundError(f"No wheel produced in {destination}")
    return wheels[-1]


def _install_wheel_to_target(wheel_path: Path, target: Path) -> None:
    install_pkg = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(target),
            str(wheel_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if install_pkg.returncode != 0:
        raise RuntimeError(
            "Failed to install hm-arch wheel into isolated target:\n"
            f"{install_pkg.stderr}"
        )


def _run_hm_arch(
    args: list[str],
    *,
    env: dict[str, str],
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-S", "-m", "hm_arch.integrations.cli.main", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        check=False,
    )


def test_wheel_contains_openclaw_plugin_payload(tmp_path_factory: pytest.TempPathFactory) -> None:
    dist_dir = tmp_path_factory.mktemp("wheel-dist")
    wheel_path = _build_wheel(dist_dir)

    with zipfile.ZipFile(wheel_path) as archive:
        names = archive.namelist()
        for relative in _PLUGIN_PAYLOAD_FILES:
            matches = [
                name
                for name in names
                if name.endswith(f"bundled_plugin/{relative}")
            ]
            assert matches, f"Wheel missing bundled plugin file: {relative}"


def test_wheel_install_openclaw_lifecycle(tmp_path_factory: pytest.TempPathFactory) -> None:
    isolated_root = tmp_path_factory.mktemp("wheel-install")
    dist_dir = isolated_root / "dist"
    dist_dir.mkdir()
    workdir = isolated_root / "workdir"
    workdir.mkdir()
    home = isolated_root / "home"
    home.mkdir()
    site_packages = isolated_root / "site-packages"
    site_packages.mkdir()

    wheel_path = _build_wheel(dist_dir)
    _install_wheel_to_target(wheel_path, site_packages)

    state_dir = home / ".openclaw"
    env = {
        "HOME": str(home),
        "OPENCLAW_STATE_DIR": str(state_dir),
        "PYTHONPATH": str(site_packages),
        "PYTHONNOUSERSITE": "1",
    }

    install = _run_hm_arch(
        ["install", "openclaw"],
        env=env,
        cwd=workdir,
    )
    assert install.returncode == 0, install.stderr
    assert "openclaw (project): installed" in install.stderr
    assert "Installed HM-Arch OpenClaw plugin" in install.stderr

    config_path = workdir / ".openclaw" / "openclaw.json"
    plugin_dir = config_path.parent / "extensions" / HM_ARCH_PLUGIN_ID
    assert config_path.exists()
    assert (plugin_dir / "openclaw.plugin.json").exists()
    assert (plugin_dir / "dist" / "index.js").exists()

    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["plugins"]["slots"]["memory"] == HM_ARCH_PLUGIN_ID

    status = _run_hm_arch(
        ["status", "openclaw"],
        env=env,
        cwd=workdir,
    )
    assert status.returncode == 0, status.stderr
    assert "openclaw (project): installed" in status.stderr

    doctor = _run_hm_arch(
        ["doctor", "openclaw"],
        env=env,
        cwd=workdir,
    )
    assert doctor.returncode == 0, doctor.stderr

    uninstall = _run_hm_arch(
        ["uninstall", "openclaw"],
        env=env,
        cwd=workdir,
    )
    assert uninstall.returncode == 0, uninstall.stderr
    assert "openclaw (project): not_installed" in uninstall.stderr
    assert not plugin_dir.exists()


def test_bundled_plugin_payload_matches_canonical_package() -> None:
    canonical = _REPO_ROOT / "packages" / "openclaw-plugin"
    bundled = _REPO_ROOT / "src" / "hm_arch" / "integrations" / "openclaw" / "bundled_plugin"
    for relative in _PLUGIN_PAYLOAD_FILES:
        assert (canonical / relative).read_bytes() == (bundled / relative).read_bytes()
