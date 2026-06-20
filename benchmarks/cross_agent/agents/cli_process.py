"""Subprocess helpers for production agent CLI invocation."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class CliInvocationResult:
    """Captured subprocess outcome for benchmark reporting."""

    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    wall_clock_ms: float
    timed_out: bool = False


class CliInvocationError(RuntimeError):
    """Raised when an agent CLI subprocess fails or times out."""

    def __init__(
        self,
        message: str,
        *,
        result: CliInvocationResult | None = None,
    ) -> None:
        super().__init__(message)
        self.result = result


def resolve_agent_executable(
    agent: str,
    *,
    override: str | None = None,
    default_names: Sequence[str] = (),
) -> str | None:
    """Resolve the agent executable from override, env, or PATH."""
    if override:
        return override
    env_key = f"HM_ARCH_BENCH_{agent.upper().replace('-', '_')}_EXECUTABLE"
    env_value = os.environ.get(env_key, "").strip()
    if env_value:
        return env_value
    for name in default_names:
        from shutil import which

        found = which(name)
        if found:
            return found
    return None


def run_cli(
    argv: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout_s: float = 120.0,
    input_text: str | None = None,
) -> CliInvocationResult:
    """Run *argv* with timeout and capture stdout/stderr/exit status."""
    from pathlib import Path

    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    t0 = time.perf_counter()
    try:
        completed = subprocess.run(
            list(argv),
            cwd=str(Path(cwd).resolve()) if cwd is not None else None,
            env=merged_env,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout_s if timeout_s > 0 else None,
            check=False,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return CliInvocationResult(
            argv=tuple(argv),
            exit_code=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            wall_clock_ms=elapsed_ms,
            timed_out=False,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        raise CliInvocationError(
            f"Agent CLI timed out after {timeout_s:.1f}s: {' '.join(argv)}",
            result=CliInvocationResult(
                argv=tuple(argv),
                exit_code=-1,
                stdout=exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
                stderr=exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or ""),
                wall_clock_ms=elapsed_ms,
                timed_out=True,
            ),
        ) from exc


def parse_benchmark_json(stdout: str) -> dict:
    """Parse JSON benchmark response from agent stdout."""
    text = stdout.strip()
    if not text:
        raise ValueError("empty stdout")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON stdout: {text[:200]}") from exc
    if not isinstance(payload, dict):
        raise ValueError("benchmark JSON must be an object")
    return payload
