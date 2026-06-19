"""HM-Arch benchmark wiring: shared DB path and single injection policy."""

from __future__ import annotations

import json
from pathlib import Path

from ..backends.hm_arch_paths import hm_arch_db_path_str
from ..types import AgentKind, BenchmarkRunConfig, MemoryBackendKind


def agent_uses_hook_recall(config: BenchmarkRunConfig) -> bool:
    """Return whether the agent CLI owns recall via installed HM-Arch hooks."""
    return (
        not config.use_mock_agent
        and config.backend is MemoryBackendKind.HM_ARCH
    )


def agent_prompt_context(config: BenchmarkRunConfig, recalled_context: str) -> str:
    """Return prompt context for the agent step (empty when hooks inject memory)."""
    if agent_uses_hook_recall(config):
        return ""
    return recalled_context


def hm_arch_cli_env(storage_dir: Path, config: BenchmarkRunConfig) -> dict[str, str]:
    """Environment variables that align agent hooks with benchmark storage."""
    if config.backend is not MemoryBackendKind.HM_ARCH:
        return {}
    return {"HM_ARCH_DB_PATH": hm_arch_db_path_str(storage_dir)}


def configure_hm_arch_agent_install(
    agent: AgentKind,
    *,
    storage_dir: Path,
    workspace: Path,
    agent_home: Path,
) -> None:
    """Point installed agent integrations at the harness HM-Arch database."""
    db_path = hm_arch_db_path_str(storage_dir)

    if agent is AgentKind.CODEX:
        from hm_arch.integrations.codex.installer import InstallScope, install_codex

        install_codex(InstallScope.PROJECT, project_root=workspace)
        return

    if agent is AgentKind.CLAUDE_CODE:
        from hm_arch.integrations.claude_code.installer import (
            InstallScope,
            install_claude_code,
        )

        install_claude_code(InstallScope.PROJECT, project_root=workspace)
        return

    if agent is AgentKind.HERMES:
        from hm_arch.integrations.hermes.config import (
            load_hermes_config,
            merge_plugin_settings,
        )
        from hm_arch.integrations.management.hermes import HermesAgentHandler

        HermesAgentHandler().install(global_install=False)
        config_path = agent_home / "config.yaml"
        config = load_hermes_config(config_path) if config_path.exists() else {}
        merged = merge_plugin_settings(config, {"db_path": db_path})
        _write_yaml_mapping(config_path, merged)
        return

    if agent is AgentKind.OPENCLAW:
        from hm_arch.integrations.management.openclaw import OpenClawAgentHandler
        from hm_arch.integrations.openclaw.config import (
            load_openclaw_config,
            merge_plugin_settings,
            resolve_openclaw_config_path,
            write_openclaw_config,
        )

        OpenClawAgentHandler().install(global_install=False)
        config_path = resolve_openclaw_config_path(global_install=False)
        config = load_openclaw_config(config_path) if config_path.exists() else {}
        merged = merge_plugin_settings(config, {"dbPath": db_path})
        write_openclaw_config(config_path, merged)
        return

    raise ValueError(f"unsupported agent for HM-Arch install: {agent}")


def _write_yaml_mapping(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml

        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return
    except ImportError:
        pass
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
