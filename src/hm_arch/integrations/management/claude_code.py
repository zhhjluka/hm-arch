"""Claude Code integration install management and diagnostics."""

from __future__ import annotations

import shutil
from pathlib import Path

from hm_arch.integrations.claude_code.installer import (
    InstallScope,
    install_claude_code,
    resolve_claude_code_paths,
    uninstall_claude_code,
)
from hm_arch.integrations.executable import is_running_as_standalone

from .hooks import expected_claude_roles, inspect_claude_hooks
from .types import Diagnostic, DiagnosticLevel, IntegrationReport, IntegrationState


class ClaudeCodeAgentHandler:
    """Manage HM-Arch Claude Code hook integration."""

    name = "claude-code"
    supports_install = True

    def install(self, *, global_install: bool) -> IntegrationReport:
        scope = InstallScope.GLOBAL if global_install else InstallScope.PROJECT
        install_claude_code(scope)
        return self.status(global_install=global_install)

    def uninstall(self, *, global_install: bool) -> IntegrationReport:
        scope = InstallScope.GLOBAL if global_install else InstallScope.PROJECT
        uninstall_claude_code(scope)
        return self.status(global_install=global_install)

    def status(self, *, global_install: bool) -> IntegrationReport:
        scope = InstallScope.GLOBAL if global_install else InstallScope.PROJECT
        paths = resolve_claude_code_paths(scope)
        roles = inspect_claude_hooks(paths.settings_json)
        expected = expected_claude_roles()
        diagnostics = _base_diagnostics(paths.root)

        if not roles:
            state = IntegrationState.NOT_INSTALLED
        elif set(roles) >= set(expected):
            state = IntegrationState.INSTALLED
        else:
            state = IntegrationState.PARTIAL
            missing = sorted(set(expected) - set(roles))
            diagnostics.append(
                Diagnostic(
                    code="claude_code.hooks.incomplete",
                    level=DiagnosticLevel.WARNING,
                    message=(
                        f"HM-Arch Claude Code hooks are partial ({scope.value}): "
                        f"missing roles {', '.join(missing)}."
                    ),
                    remedy=(
                        f"Run: hm-arch install claude-code"
                        f"{' --global' if global_install else ''}"
                    ),
                )
            )

        return IntegrationReport(
            agent=self.name,
            scope=scope.value,
            state=state,
            config_root=paths.root,
            installed_roles=roles,
            diagnostics=tuple(diagnostics),
        )

    def doctor(self, *, global_install: bool) -> IntegrationReport:
        report = self.status(global_install=global_install)
        diagnostics = list(report.diagnostics)
        if report.state == IntegrationState.NOT_INSTALLED:
            diagnostics.append(
                Diagnostic(
                    code="claude_code.not_installed",
                    level=DiagnosticLevel.ERROR,
                    message=(
                        "HM-Arch Claude Code hooks are not installed for this scope."
                    ),
                    remedy=(
                        f"Run: hm-arch install claude-code"
                        f"{' --global' if global_install else ''}"
                    ),
                )
            )
        return IntegrationReport(
            agent=report.agent,
            scope=report.scope,
            state=report.state,
            config_root=report.config_root,
            installed_roles=report.installed_roles,
            diagnostics=tuple(diagnostics),
        )


def _base_diagnostics(config_root: Path) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    hm_arch = shutil.which("hm-arch")
    if hm_arch:
        diagnostics.append(
            Diagnostic(
                code="hm_arch.executable.found",
                level=DiagnosticLevel.INFO,
                message=f"hm-arch is on PATH at {hm_arch}.",
            )
        )
    elif is_running_as_standalone():
        diagnostics.append(
            Diagnostic(
                code="hm_arch.executable.standalone",
                level=DiagnosticLevel.INFO,
                message="HM-Arch standalone executable is available for Claude Code hooks.",
            )
        )
    else:
        diagnostics.append(
            Diagnostic(
                code="hm_arch.executable.missing",
                level=DiagnosticLevel.WARNING,
                message=(
                    "hm-arch is not on PATH; Claude Code hooks will fall back to "
                    "python -m hm_arch.integrations.cli."
                ),
                remedy="Install hm-arch with pip or pipx and ensure its bin directory is on PATH.",
            )
        )

    claude_cli = shutil.which("claude")
    if claude_cli:
        diagnostics.append(
            Diagnostic(
                code="claude_code.cli.found",
                level=DiagnosticLevel.INFO,
                message=f"claude CLI found at {claude_cli}.",
            )
        )
    else:
        diagnostics.append(
            Diagnostic(
                code="claude_code.cli.missing",
                level=DiagnosticLevel.WARNING,
                message="claude executable was not found on PATH.",
                remedy=(
                    "Install Claude Code CLI or verify your shell PATH includes the binary."
                ),
            )
        )

    if not config_root.exists():
        diagnostics.append(
            Diagnostic(
                code="claude_code.config_root.missing",
                level=DiagnosticLevel.INFO,
                message=(
                    f"Claude Code config directory does not exist yet: {config_root}."
                ),
            )
        )
    return diagnostics
