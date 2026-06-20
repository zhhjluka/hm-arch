#!/usr/bin/env python3
"""Run OpenClaw end-to-end verification and capture handoff artifacts."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = REPO_ROOT / "artifacts" / "openclaw-e2e"


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    print(f"+ {' '.join(command)}", flush=True)
    return subprocess.run(
        command,
        cwd=cwd or REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-node",
        action="store_true",
        help="Skip @hm-arch/openclaw-plugin Node E2E tests",
    )
    parser.add_argument(
        "--skip-full-suite",
        action="store_true",
        help="Skip full offline pytest suite",
    )
    args = parser.parse_args()

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    log_path = ARTIFACTS / "run.log"
    results: dict[str, object] = {"steps": []}

    def record(step: str, proc: subprocess.CompletedProcess[str]) -> None:
        entry = {
            "step": step,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
        results["steps"].append(entry)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n=== {step} (exit {proc.returncode}) ===\n")
            if proc.stdout:
                handle.write(proc.stdout)
            if proc.stderr:
                handle.write(proc.stderr)

    py_e2e = _run(
        [sys.executable, "-m", "pytest", "tests/test_integrations_openclaw_e2e.py", "-q"],
    )
    record("python-openclaw-e2e", py_e2e)
    if py_e2e.returncode != 0:
        (ARTIFACTS / "results.json").write_text(
            json.dumps(results, indent=2) + "\n",
            encoding="utf-8",
        )
        print(py_e2e.stdout)
        print(py_e2e.stderr, file=sys.stderr)
        return py_e2e.returncode

    focused = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_integrations_openclaw_manage.py",
            "tests/test_integrations_openclaw_sidecar.py",
            "tests/test_integrations_openclaw_wheel.py",
            "-q",
        ],
    )
    record("python-openclaw-focused", focused)
    if focused.returncode != 0:
        (ARTIFACTS / "results.json").write_text(
            json.dumps(results, indent=2) + "\n",
            encoding="utf-8",
        )
        print(focused.stdout)
        print(focused.stderr, file=sys.stderr)
        return focused.returncode

    if not args.skip_node:
        plugin_dir = REPO_ROOT / "packages" / "openclaw-plugin"
        npm_ci = _run(["npm", "ci"], cwd=plugin_dir)
        record("npm-ci-openclaw-plugin", npm_ci)
        if npm_ci.returncode != 0:
            (ARTIFACTS / "results.json").write_text(
                json.dumps(results, indent=2) + "\n",
                encoding="utf-8",
            )
            print(npm_ci.stderr, file=sys.stderr)
            return npm_ci.returncode

        node_test = _run(["npm", "test"], cwd=plugin_dir)
        record("npm-test-openclaw-plugin", node_test)
        if node_test.returncode != 0:
            (ARTIFACTS / "results.json").write_text(
                json.dumps(results, indent=2) + "\n",
                encoding="utf-8",
            )
            print(node_test.stdout)
            print(node_test.stderr, file=sys.stderr)
            return node_test.returncode

    if not args.skip_full_suite:
        full = _run([sys.executable, "-m", "pytest", "-q"])
        record("python-full-offline-suite", full)
        if full.returncode != 0:
            (ARTIFACTS / "results.json").write_text(
                json.dumps(results, indent=2) + "\n",
                encoding="utf-8",
            )
            print(full.stdout)
            print(full.stderr, file=sys.stderr)
            return full.returncode

    from hm_arch._version import __version__

    node_version = None
    node_probe = _run(["node", "--version"])
    if node_probe.returncode == 0:
        node_version = node_probe.stdout.strip()

    handoff = {
        "hm_arch_version": __version__,
        "python_version": sys.version.split()[0],
        "node_version": node_version,
        "artifacts_dir": str(ARTIFACTS),
        "platform": sys.platform,
        "notes": [
            "All OpenClaw E2E tests use isolated OPENCLAW_STATE_DIR or tmp_path homes.",
            "Real OpenClaw gateway restart is documented in docs/openclaw-e2e-smoke.md.",
        ],
    }
    (ARTIFACTS / "handoff.json").write_text(json.dumps(handoff, indent=2) + "\n", encoding="utf-8")
    (ARTIFACTS / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(handoff, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
