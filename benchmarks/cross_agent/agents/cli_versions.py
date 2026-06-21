"""Collect agent CLI and provider package versions for benchmark provenance."""

from __future__ import annotations

import importlib.metadata
import platform
import sys
from typing import Any

from ..types import AgentKind, MemoryBackendKind
from .cli_process import run_cli


def _probe_executable_version(executable: str) -> str | None:
    """Best-effort version string from common CLI flags."""
    for argv in (
        [executable, "--version"],
        [executable, "-V"],
        [executable, "version"],
    ):
        try:
            result = run_cli(argv, timeout_s=5.0)
        except Exception:  # noqa: BLE001 — version probing is best-effort
            continue
        combined = f"{result.stdout}\n{result.stderr}".strip()
        if result.exit_code == 0 and combined:
            return combined.splitlines()[0].strip()
    return None


def _package_version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def collect_provider_versions(backend: MemoryBackendKind) -> dict[str, str | None]:
    """Return installed provider package versions for *backend*."""
    if backend is MemoryBackendKind.MEM0:
        return {"mem0ai": _package_version("mem0ai")}
    if backend is MemoryBackendKind.OPENVIKING:
        return {"openviking": _package_version("openviking")}
    if backend is MemoryBackendKind.HM_ARCH:
        return {"hm_arch": _package_version("hm-arch")}
    return {}


def collect_agent_cli_version(
    agent: AgentKind,
    *,
    executable: str | None,
) -> dict[str, Any]:
    """Return CLI executable path and version probe for *agent*."""
    if executable is None:
        return {
            "agent": agent.value,
            "executable": None,
            "version": None,
            "probe_status": "executable_not_found",
        }
    version = _probe_executable_version(executable)
    return {
        "agent": agent.value,
        "executable": executable,
        "version": version,
        "probe_status": "ok" if version else "version_unavailable",
    }


def collect_runtime_provenance(
    *,
    agent: AgentKind,
    backend: MemoryBackendKind,
    executable: str | None,
    cli_mode: str | None = None,
) -> dict[str, Any]:
    """Bundle environment, CLI, and provider version metadata for a run."""
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "agent_cli": collect_agent_cli_version(agent, executable=executable),
        "provider_packages": collect_provider_versions(backend),
        "cli_mode": cli_mode,
    }
