"""Hermes Agent integration diagnostics (config inspection only)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from hm_arch.integrations.hermes.config import (
    HM_ARCH_PROVIDER_NAME,
    detect_external_provider_conflict,
    load_hermes_config,
    read_memory_provider,
    read_plugin_settings,
    resolve_db_path,
)

from .types import Diagnostic, DiagnosticLevel, IntegrationReport, IntegrationState

_HERMES_INSTALL_REMEDY = (
    "Hermes uses native plugin registration; configure memory.provider and "
    "plugins.hm-arch in Hermes config.yaml. Run `hm-arch status hermes` and "
    "`hm-arch doctor hermes` to inspect configuration."
)


def resolve_hermes_home() -> Path:
    """Return the Hermes home directory from HERMES_HOME or the default."""
    raw = os.environ.get("HERMES_HOME", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".hermes"


class HermesAgentHandler:
    """Inspect Hermes HM-Arch memory provider configuration."""

    name = "hermes"
    supports_install = False

    def install(self, *, global_install: bool) -> IntegrationReport:
        del global_install
        return IntegrationReport(
            agent=self.name,
            scope=None,
            state=IntegrationState.UNSUPPORTED,
            diagnostics=(
                Diagnostic(
                    code="hermes.install.unsupported",
                    level=DiagnosticLevel.ERROR,
                    message=(
                        "hm-arch install hermes is not supported; Hermes registers "
                        "the HM-Arch memory provider through its plugin system."
                    ),
                    remedy=_HERMES_INSTALL_REMEDY,
                ),
            ),
        )

    def uninstall(self, *, global_install: bool) -> IntegrationReport:
        del global_install
        return IntegrationReport(
            agent=self.name,
            scope=None,
            state=IntegrationState.UNSUPPORTED,
            diagnostics=(
                Diagnostic(
                    code="hermes.uninstall.unsupported",
                    level=DiagnosticLevel.ERROR,
                    message=(
                        "hm-arch uninstall hermes is not supported; remove HM-Arch "
                        "plugin settings from Hermes config.yaml manually if needed."
                    ),
                    remedy=(
                        "Edit Hermes config.yaml and clear plugins.hm-arch settings "
                        "without changing unrelated memory providers."
                    ),
                ),
            ),
        )

    def status(self, *, global_install: bool) -> IntegrationReport:
        del global_install
        home = resolve_hermes_home()
        config_path = home / "config.yaml"
        diagnostics = _base_diagnostics(home, config_path)

        if not config_path.exists():
            return IntegrationReport(
                agent=self.name,
                scope=None,
                state=IntegrationState.NOT_INSTALLED,
                config_root=home,
                diagnostics=tuple(diagnostics),
            )

        try:
            config = load_hermes_config(config_path)
        except ValueError as exc:
            diagnostics.append(
                Diagnostic(
                    code="hermes.config.invalid",
                    level=DiagnosticLevel.ERROR,
                    message=str(exc),
                    remedy=f"Fix YAML syntax in {config_path}.",
                )
            )
            return IntegrationReport(
                agent=self.name,
                scope=None,
                state=IntegrationState.PARTIAL,
                config_root=home,
                diagnostics=tuple(diagnostics),
            )

        provider = read_memory_provider(config)
        plugin_settings = read_plugin_settings(config)
        conflict = detect_external_provider_conflict(config)

        if conflict is not None:
            diagnostics.append(
                Diagnostic(
                    code="hermes.provider.conflict",
                    level=DiagnosticLevel.ERROR,
                    message=str(conflict),
                    remedy=(
                        "Set memory.provider to 'hm-arch' explicitly in config.yaml "
                        "if you intend to switch providers."
                    ),
                )
            )
            state = IntegrationState.PARTIAL
        elif provider == HM_ARCH_PROVIDER_NAME:
            state = IntegrationState.INSTALLED
            diagnostics.append(
                Diagnostic(
                    code="hermes.provider.active",
                    level=DiagnosticLevel.INFO,
                    message=f"Hermes memory.provider is set to {provider!r}.",
                )
            )
        elif provider in (None, "", "builtin"):
            state = IntegrationState.NOT_INSTALLED
            diagnostics.append(
                Diagnostic(
                    code="hermes.provider.not_configured",
                    level=DiagnosticLevel.INFO,
                    message=(
                        "Hermes memory.provider is not set to hm-arch; plugin settings "
                        "may still be present."
                    ),
                    remedy=_HERMES_INSTALL_REMEDY,
                )
            )
        else:
            state = IntegrationState.PARTIAL
            diagnostics.append(
                Diagnostic(
                    code="hermes.provider.other",
                    level=DiagnosticLevel.WARNING,
                    message=f"Hermes memory.provider is {provider!r}.",
                    remedy=_HERMES_INSTALL_REMEDY,
                )
            )

        if plugin_settings:
            diagnostics.append(
                Diagnostic(
                    code="hermes.plugin.configured",
                    level=DiagnosticLevel.INFO,
                    message=f"plugins.hm-arch settings found: {sorted(plugin_settings)}.",
                )
            )

        db_path = resolve_db_path(home, plugin_settings)
        db_file = Path(db_path)
        if db_file.exists():
            diagnostics.append(
                Diagnostic(
                    code="hermes.db.present",
                    level=DiagnosticLevel.INFO,
                    message=f"HM-Arch database exists at {db_path}.",
                )
            )
        else:
            diagnostics.append(
                Diagnostic(
                    code="hermes.db.missing",
                    level=DiagnosticLevel.INFO,
                    message=f"HM-Arch database not created yet at {db_path}.",
                )
            )

        roles: tuple[str, ...] = ()
        if provider == HM_ARCH_PROVIDER_NAME:
            roles = ("memory-provider",)

        return IntegrationReport(
            agent=self.name,
            scope=None,
            state=state,
            config_root=home,
            installed_roles=roles,
            diagnostics=tuple(diagnostics),
        )

    def doctor(self, *, global_install: bool) -> IntegrationReport:
        report = self.status(global_install=global_install)
        diagnostics = list(report.diagnostics)
        conflict_codes = {"hermes.provider.conflict", "hermes.config.invalid"}
        if any(item.code in conflict_codes for item in diagnostics):
            return IntegrationReport(
                agent=report.agent,
                scope=report.scope,
                state=report.state,
                config_root=report.config_root,
                installed_roles=report.installed_roles,
                diagnostics=tuple(diagnostics),
            )
        if report.state != IntegrationState.INSTALLED:
            diagnostics.append(
                Diagnostic(
                    code="hermes.not_configured",
                    level=DiagnosticLevel.WARNING,
                    message=(
                        "Hermes is not fully configured to use HM-Arch as the active "
                        "memory provider."
                    ),
                    remedy=_HERMES_INSTALL_REMEDY,
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


def _base_diagnostics(home: Path, config_path: Path) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    hermes_cli = shutil.which("hermes")
    if hermes_cli:
        diagnostics.append(
            Diagnostic(
                code="hermes.cli.found",
                level=DiagnosticLevel.INFO,
                message=f"hermes CLI found at {hermes_cli}.",
            )
        )
    else:
        diagnostics.append(
            Diagnostic(
                code="hermes.cli.missing",
                level=DiagnosticLevel.WARNING,
                message="hermes executable was not found on PATH.",
                remedy="Install Hermes Agent CLI or verify HERMES_HOME and PATH.",
            )
        )

    diagnostics.append(
        Diagnostic(
            code="hermes.home",
            level=DiagnosticLevel.INFO,
            message=f"Hermes home: {home} (config: {config_path}).",
        )
    )
    return diagnostics
