#!/usr/bin/env python3
"""Build the HM-Arch standalone CLI executable with PyInstaller."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_output(repo_root: Path) -> Path:
    name = "hm-arch.exe" if sys.platform == "win32" else "hm-arch"
    return repo_root / "dist" / "standalone" / name


def build_standalone(*, clean: bool = False, output: Path | None = None) -> Path:
    """Run PyInstaller and return the built executable path."""
    repo_root = _repo_root()
    spec_path = repo_root / "packaging" / "hm-arch.spec"
    dist_dir = repo_root / "dist" / "standalone"
    work_dir = repo_root / "build" / "pyinstaller"

    if clean:
        shutil.rmtree(dist_dir, ignore_errors=True)
        shutil.rmtree(work_dir, ignore_errors=True)

    dist_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
        str(spec_path),
    ]
    subprocess.run(cmd, check=True, cwd=repo_root)

    built = output or _default_output(repo_root)
    if built != _default_output(repo_root):
        built.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_default_output(repo_root), built)
    return built


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove previous PyInstaller output before building.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional destination path for the built executable.",
    )
    args = parser.parse_args(argv)

    built = build_standalone(clean=args.clean, output=args.output)
    print(f"Built standalone executable: {built}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
