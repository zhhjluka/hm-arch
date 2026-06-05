#!/usr/bin/env python3
"""Verify coordinated release versions across Python, npm, and generated artifacts (MEM-64)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION_PY = REPO_ROOT / "src" / "hm_arch" / "_version.py"
PACKAGE_JSON = REPO_ROOT / "packages" / "installer" / "package.json"
BUNDLED_JSON = REPO_ROOT / "packages" / "installer" / "src" / "bundled-version.json"
INSTALLER_JSON = REPO_ROOT / "packages" / "installer" / "src" / "installer-version.json"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def read_python_version() -> str:
    text = VERSION_PY.read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    if not match:
        raise SystemExit(f"Could not parse __version__ from {VERSION_PY}")
    return match.group(1)


def read_json_version(path: Path, key: str = "version") -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    value = payload.get(key)
    if not isinstance(value, str):
        raise SystemExit(f"Invalid {key} in {path}")
    return value


def main() -> int:
    python_version = read_python_version()
    npm_version = read_json_version(PACKAGE_JSON)
    bundled_version = read_json_version(BUNDLED_JSON)
    installer_version = read_json_version(INSTALLER_JSON)

    errors: list[str] = []
    for label, value in [
        ("python", python_version),
        ("npm", npm_version),
        ("bundled", bundled_version),
        ("installer-generated", installer_version),
    ]:
        if not SEMVER.match(value):
            errors.append(f"{label} version is not semver: {value!r}")

    if python_version != bundled_version:
        errors.append(
            f"bundled hm-arch version mismatch: {bundled_version} != {python_version}",
        )
    if npm_version != installer_version:
        errors.append(
            f"installer version mismatch: {installer_version} != npm {npm_version}",
        )
    if npm_version != python_version:
        errors.append(
            "npm package version differs from Python __version__ "
            f"({npm_version} != {python_version}); record intentional skew in release notes",
        )

    if errors:
        print("Release version coordination check FAILED:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(
        "Release version coordination OK: "
        f"hm-arch=={python_version}, @hm-arch/installer=={npm_version}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
