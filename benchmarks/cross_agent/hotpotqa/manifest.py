"""Run manifest and CLI provenance for HotpotQA matrix execution (MEM-77)."""

from __future__ import annotations

import json
import os
import platform
import stat
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..agents.cli_process import resolve_agent_executable, run_cli
from ..fixtures.hotpotqa import (
    HOTPOTQA_SUBSET_VERSION,
    compute_subset_hash,
    load_hotpotqa_config,
)
from ..types import AgentKind

REPO_ROOT = Path(__file__).resolve().parents[3]
FAKE_AGENT_CLI = REPO_ROOT / "tests" / "fixtures" / "fake_agent_cli.py"

_AGENT_EXECUTABLE_NAMES: dict[AgentKind, tuple[str, ...]] = {
    AgentKind.CODEX: ("codex",),
    AgentKind.CLAUDE_CODE: ("claude",),
    AgentKind.HERMES: ("hermes",),
    AgentKind.OPENCLAW: ("openclaw",),
}

_AGENT_INVOCATION_TEMPLATES: dict[AgentKind, str] = {
    AgentKind.CODEX: "codex exec --json [--disable memories] <prompt>",
    AgentKind.CLAUDE_CODE: "claude -p <prompt> --output-format json",
    AgentKind.HERMES: "hermes -z <prompt>",
    AgentKind.OPENCLAW: (
        "openclaw agent --agent main --session-key <id> --message <prompt> --local --json"
    ),
}


@dataclass(frozen=True)
class ResolvedExecutable:
    """Resolved agent CLI for one matrix coordinate."""

    path: str
    source: str
    is_test_double: bool
    cli_mode: str | None = None
    version_probe: dict[str, Any] | None = None


def write_fake_agent_wrapper(path: Path) -> str:
    """Write a shell wrapper that invokes the pinned fake agent CLI double."""
    script = f"""#!/bin/sh
exec {sys.executable} {FAKE_AGENT_CLI} "$@"
"""
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def probe_cli_version(executable: str, agent: AgentKind) -> dict[str, Any]:
    """Best-effort version/help probe for reporting."""
    probes: list[list[str]] = []
    if agent is AgentKind.CODEX:
        probes = [[executable, "--version"], [executable, "exec", "--help"]]
    elif agent is AgentKind.CLAUDE_CODE:
        probes = [[executable, "--version"], [executable, "--help"]]
    elif agent is AgentKind.HERMES:
        probes = [[executable, "--version"], [executable, "--help"]]
    elif agent is AgentKind.OPENCLAW:
        probes = [[executable, "--version"], [executable, "agent", "--help"]]

    for argv in probes:
        try:
            result = run_cli(argv, timeout_s=5.0)
        except Exception as exc:  # noqa: BLE001 — probe only
            continue
        combined = f"{result.stdout}\n{result.stderr}".strip()
        if combined:
            return {
                "argv": argv,
                "exit_code": result.exit_code,
                "output": combined[:500],
            }
    return {"argv": None, "exit_code": None, "output": None}


def _portable_path(path: str) -> str:
    """Prefer repo-relative paths in committed benchmark manifests."""
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(resolved)


def resolve_comparison_executable(
    agent: AgentKind,
    *,
    override: str | None = None,
    fake_wrapper: str | None = None,
) -> ResolvedExecutable:
    """Resolve a production or documented test-double CLI for comparison runs."""
    if override:
        path = override
        source = "override"
        is_test_double = "fake_agent_cli" in path or path.endswith("fake-agent-cli")
    else:
        path = resolve_agent_executable(
            agent.value,
            default_names=_AGENT_EXECUTABLE_NAMES[agent],
        )
        if path is not None:
            source = "path"
            is_test_double = False
        elif fake_wrapper is not None:
            path = fake_wrapper
            source = "fake_double"
            is_test_double = True
        else:
            path = write_fake_agent_wrapper(REPO_ROOT / ".cache" / f"fake-{agent.value}-cli")
            source = "fake_double"
            is_test_double = True

    cli_mode: str | None = None
    if is_test_double:
        cli_mode = "real"
    else:
        try:
            result = run_cli([path, "hm-arch-benchmark", "--help"], timeout_s=5.0)
            if result.exit_code == 0:
                cli_mode = "benchmark"
        except Exception:  # noqa: BLE001 — probe only
            cli_mode = None
        if cli_mode is None:
            cli_mode = "real"

    version_probe = probe_cli_version(path, agent)
    return ResolvedExecutable(
        path=path,
        source=source,
        is_test_double=is_test_double,
        cli_mode=cli_mode,
        version_probe=version_probe,
    )


def _hm_arch_version() -> str | None:
    try:
        import hm_arch

        return getattr(hm_arch, "__version__", None)
    except Exception:  # noqa: BLE001 — optional for manifest
        return None


def build_run_manifest(
    *,
    output_root: Path,
    seed: int,
    execution_mode: str,
    use_mock_agent: bool,
    command: str,
    agent_executables: dict[str, ResolvedExecutable] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the top-level run manifest persisted beside matrix artifacts."""
    config = load_hotpotqa_config()
    manifest: dict[str, Any] = {
        "benchmark": "hotpotqa",
        "issue": "MEM-77",
        "execution_mode": execution_mode,
        "use_mock_agent": use_mock_agent,
        "command": command,
        "subset_version": HOTPOTQA_SUBSET_VERSION,
        "subset_hash": compute_subset_hash(),
        "seed": seed,
        "answer_prompt_template": config["answer_prompt_template"],
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "hm_arch_version": _hm_arch_version(),
            "cwd": str(Path.cwd()),
        },
        "agent_invocation_templates": {
            agent.value: template for agent, template in _AGENT_INVOCATION_TEMPLATES.items()
        },
        "output_root": str(output_root),
    }
    if agent_executables:
        manifest["agent_executables"] = {
            agent: {
                **{
                    **asdict(resolved),
                    "path": _portable_path(resolved.path),
                },
                "invocation_template": _AGENT_INVOCATION_TEMPLATES[AgentKind(agent)],
            }
            for agent, resolved in agent_executables.items()
        }
    if extra:
        manifest.update(extra)
    return manifest


def write_run_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def collect_agent_executables(
    agents: tuple[AgentKind, ...],
    *,
    override: str | None = None,
    cache_dir: Path | None = None,
) -> dict[str, ResolvedExecutable]:
    """Resolve executables for all agents participating in a matrix run."""
    cache = cache_dir or (REPO_ROOT / ".cache" / "hotpotqa-cli")
    cache.mkdir(parents=True, exist_ok=True)
    fake_wrapper = write_fake_agent_wrapper(cache / "fake-agent-cli")
    resolved: dict[str, ResolvedExecutable] = {}
    for agent in agents:
        resolved[agent.value] = resolve_comparison_executable(
            agent,
            override=override,
            fake_wrapper=fake_wrapper,
        )
    return resolved
