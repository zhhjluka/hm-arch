#!/usr/bin/env python3
"""Smoke-test a standalone hm-arch release artifact without pytest."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hm_arch import EventType, HMArch, MemoryConfig  # noqa: E402


def _run_executable(
    executable: Path,
    args: list[str],
    *,
    env: dict[str, str],
    stdin: str | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(executable), *args],
        input=stdin,
        text=True,
        capture_output=True,
        cwd=cwd or _REPO_ROOT,
        env={**os.environ, **env},
    )


def _seed_memory(db_path: str) -> None:
    config = MemoryConfig(db_path=db_path, replay_sample_ratio=1.0)
    with HMArch(config=config) as memory:
        memory.add(
            "Repository uses uv and pytest for offline verification",
            event_type=EventType.OBSERVATION,
            importance=0.85,
        )


def smoke_standalone_artifact(executable: Path) -> None:
    if not executable.is_file():
        raise FileNotFoundError(f"Executable not found: {executable}")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "artifact_smoke.db")
        env = {"HM_ARCH_DB_PATH": db_path, "PATH": ""}
        _seed_memory(db_path)

        help_proc = _run_executable(executable, ["--help"], env={})
        if help_proc.returncode != 0:
            raise RuntimeError(f"--help failed:\n{help_proc.stderr}")
        if "recall" not in help_proc.stdout:
            raise RuntimeError("--help output missing recall subcommand")

        recall_proc = _run_executable(
            executable,
            ["recall"],
            env=env,
            stdin=json.dumps({"task": "offline pytest"}),
        )
        if recall_proc.returncode != 0:
            raise RuntimeError(f"recall failed:\n{recall_proc.stderr}")
        recall_payload = json.loads(recall_proc.stdout)
        if not recall_payload.get("ok"):
            raise RuntimeError(f"recall returned not ok: {recall_payload}")
        if recall_payload.get("result_count", 0) < 1:
            raise RuntimeError("recall returned no results for seeded memory")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "executable",
        type=Path,
        help="Path to the standalone hm-arch executable artifact.",
    )
    args = parser.parse_args(argv)
    smoke_standalone_artifact(args.executable.resolve())
    print(f"Standalone artifact smoke test passed: {args.executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
