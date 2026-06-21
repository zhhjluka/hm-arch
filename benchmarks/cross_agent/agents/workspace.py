"""Workspace and agent-home isolation for cross-agent benchmarks."""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from ..types import AgentKind


_AGENT_HOME_ENV: dict[AgentKind, str] = {
    AgentKind.CODEX: "CODEX_HOME",
    AgentKind.CLAUDE_CODE: "CLAUDE_CONFIG_DIR",
    AgentKind.HERMES: "HERMES_HOME",
    AgentKind.OPENCLAW: "OPENCLAW_STATE_DIR",
}

_CREDENTIAL_ALLOWLIST: dict[AgentKind, tuple[tuple[str, str], ...]] = {
    AgentKind.CODEX: ((".codex/auth.json", "auth.json"),),
    AgentKind.HERMES: (
        (".hermes/.env", ".env"),
        (".hermes/auth.json", "auth.json"),
        (".hermes/auth", "auth"),
    ),
}


def _stage_cli_credentials(
    agent: AgentKind,
    *,
    source_home: Path,
    agent_home: Path,
) -> None:
    """Copy only agent authentication material into an isolated home."""
    for source_relative, destination_relative in _CREDENTIAL_ALLOWLIST.get(agent, ()):
        source = source_home / source_relative
        destination = agent_home / destination_relative
        if source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        elif source.is_dir():
            shutil.copytree(source, destination)


@dataclass
class AgentWorkspace:
    """Isolated filesystem layout for one benchmark run."""

    agent: AgentKind
    run_id: str
    root: Path
    workspace: Path
    agent_home: Path
    _previous_env: dict[str, str | None] = field(default_factory=dict, repr=False)
    _active: bool = False

    @classmethod
    def create(
        cls,
        agent: AgentKind,
        *,
        run_id: str | None = None,
        parent: Path | None = None,
        credential_source_home: Path | None = None,
    ) -> AgentWorkspace:
        run = run_id or uuid.uuid4().hex[:12]
        prefix = f"hm-arch-bench-{agent.value}-{run}-"
        if parent is not None:
            root = parent.resolve() / "agent_workspace"
            if root.exists():
                shutil.rmtree(root, ignore_errors=True)
            root.mkdir(parents=True, exist_ok=True)
        else:
            root = Path(tempfile.mkdtemp(prefix=prefix))
        workspace = root / "workspace"
        agent_home = root / "agent_home"
        workspace.mkdir()
        agent_home.mkdir()
        _stage_cli_credentials(
            agent,
            source_home=credential_source_home or Path.home(),
            agent_home=agent_home,
        )
        return cls(
            agent=agent,
            run_id=run,
            root=root,
            workspace=workspace,
            agent_home=agent_home,
        )

    def agent_home_env_var(self) -> str:
        return _AGENT_HOME_ENV[self.agent]

    def activate(self) -> None:
        """Point agent-specific home env vars at the isolated directory."""
        if self._active:
            return
        env_name = self.agent_home_env_var()
        self._previous_env[env_name] = os.environ.get(env_name)
        os.environ[env_name] = str(self.agent_home)
        self._previous_env["PWD"] = os.getcwd()
        os.chdir(self.workspace)
        self._active = True

    def deactivate(self) -> None:
        """Restore previous environment variables."""
        if not self._active:
            return
        previous_pwd = self._previous_env.get("PWD")
        if previous_pwd and Path(previous_pwd).exists():
            os.chdir(previous_pwd)
        elif self.root.parent.exists():
            os.chdir(self.root.parent)
        else:
            os.chdir(Path.cwd().anchor or "/")
        for key, value in self._previous_env.items():
            if key == "PWD":
                continue
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._previous_env.clear()
        self._active = False

    def cleanup(self) -> None:
        """Deactivate and remove temporary directories."""
        self.deactivate()
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self) -> AgentWorkspace:
        self.activate()
        return self

    def __exit__(self, *args: object) -> None:
        self.cleanup()


def isolated_workspace(
    agent: AgentKind,
    *,
    run_id: str | None = None,
    parent: Path | None = None,
) -> Iterator[AgentWorkspace]:
    """Context manager yielding an activated, cleaned-up workspace."""
    ws = AgentWorkspace.create(agent, run_id=run_id, parent=parent)
    try:
        ws.activate()
        yield ws
    finally:
        ws.cleanup()
