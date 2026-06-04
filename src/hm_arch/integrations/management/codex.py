"""Codex integration install management and diagnostics."""

from __future__ import annotations

import shutil
from pathlib import Path

from hm_arch.integrations.codex.config_toml import hooks_feature_enabled
from hm_arch.integrations.codex.installer import (
    InstallScope,
    install_codex,
    resolve_codex_paths,
    uninstall_codex,
)

from .hooks import expected_codex_roles, inspect_codex_hooks
from .types import Diagnostic, DiagnosticLevel, IntegrationReport, IntegrationState


class CodexAgentHandler:
    """Manage HM-Arch Codex hook integration."""

    name = "codex"
    supports_install = True

    def install(self, *, global_install: bool) -> IntegrationReport:
        scope = InstallScope.GLOBAL if global_install else InstallScope.PROJECT
        install_codex(scope)
        return self.status(global_install=global_install)

    def uninstall(self, *, global_install: bool) -> IntegrationReport:
        scope = InstallScope.GLOBAL if global_install else InstallScope.PROJECT
        uninstall_codex(scope)
        return self.status(global_install=global_install)

    def status(self, *, global_install: bool) -> IntegrationReport:
        scope = InstallScope.GLOBAL if global_install else InstallScope.PROJECT
        paths = resolve_codex_paths(scope)
        roles = inspect_codex_hooks(paths.hooks_json)
        expected = expected_codex_roles()
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
                    code="codex.hooks.incomplete",
                    level=DiagnosticLevel.WARNING,
                    message=(
                        f"HM-Arch Codex hooks are partial ({scope.value}): "
                        f"missing roles {', '.join(missing)}."
                    ),
                    remedy=f"Run: hm-arch install codex{' --global' if global_install else ''}",
                )
            )

        if paths.hooks_json.exists() and paths.config_toml.exists():
            config_text = paths.config_toml.read_text(encoding="utf-8")
            if not hooks_feature_enabled(config_text):
                diagnostics.append(
                    Diagnostic(
                        code="codex.hooks.disabled",
                        level=DiagnosticLevel.ERROR,
                        message=(
                            f"Codex hooks feature flag is not enabled in {paths.config_toml}."
                        ),
                        remedy=(
                            f"Run: hm-arch install codex{' --global' if global_install else ''} "
                            "to enable [features].hooks = true."
                        ),
                    )
                )
        elif state != IntegrationState.NOT_INSTALLED and not paths.config_toml.exists():
            diagnostics.append(
                Diagnostic(
                    code="codex.config.missing",
                    level=DiagnosticLevel.WARNING,
                    message=f"Codex config.toml is missing at {paths.config_toml}.",
                    remedy=(
                        f"Run: hm-arch install codex{' --global' if global_install else ''}"
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
                    code="codex.not_installed",
                    level=DiagnosticLevel.ERROR,
                    message="HM-Arch Codex hooks are not installed for this scope.",
                    remedy=(
                        f"Run: hm-arch install codex"
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
    else:
        diagnostics.append(
            Diagnostic(
                code="hm_arch.executable.missing",
                level=DiagnosticLevel.WARNING,
                message=(
                    "hm-arch is not on PATH; Codex hooks will fall back to "
                    "python -m hm_arch.integrations.cli."
                ),
                remedy="Install hm-arch with pip or pipx and ensure its bin directory is on PATH.",
            )
        )

    codex_cli = shutil.which("codex")
    if codex_cli:
        diagnostics.append(
            Diagnostic(
                code="codex.cli.found",
                level=DiagnosticLevel.INFO,
                message=f"codex CLI found at {codex_cli}.",
            )
        )
    else:
        diagnostics.append(
            Diagnostic(
                code="codex.cli.missing",
                level=DiagnosticLevel.WARNING,
                message="codex executable was not found on PATH.",
                remedy="Install Codex CLI or verify your shell PATH includes the Codex binary.",
            )
        )

    if not config_root.exists():
        diagnostics.append(
            Diagnostic(
                code="codex.config_root.missing",
                level=DiagnosticLevel.INFO,
                message=f"Codex config directory does not exist yet: {config_root}.",
            )
        )
    return diagnostics
