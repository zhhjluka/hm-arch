"""Hermes Agent integration diagnostics (config inspection only)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from hm_arch.integrations.hermes.config import (
    DEFAULT_DB_FILENAME,
    HM_ARCH_PROVIDER_NAME,
    detect_external_provider_conflict,
    load_hermes_config,
    merge_plugin_settings,
    read_memory_provider,
    read_plugin_settings,
    resolve_db_path,
)
from hm_arch.storage.sqlite import SQLiteStore

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
    supports_install = True

    def install(self, *, global_install: bool) -> IntegrationReport:
        del global_install
        home = resolve_hermes_home()
        config_path = home / "config.yaml"
        diagnostics = _base_diagnostics(home, config_path)

        try:
            config = load_hermes_config(config_path) if config_path.exists() else {}
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
                return IntegrationReport(
                    agent=self.name,
                    scope=None,
                    state=IntegrationState.PARTIAL,
                    config_root=home,
                    diagnostics=tuple(diagnostics),
                )

            plugin_settings = read_plugin_settings(config)
            db_path_setting = plugin_settings.get("db_path", DEFAULT_DB_FILENAME)
            merged = merge_plugin_settings(config, {"db_path": db_path_setting})
            memory = merged.setdefault("memory", {})
            if not isinstance(memory, dict):
                raise ValueError("config.memory must be a mapping")
            memory["provider"] = HM_ARCH_PROVIDER_NAME
            _write_hermes_config(config_path, merged)
            diagnostics.append(
                Diagnostic(
                    code="hermes.config.updated",
                    level=DiagnosticLevel.INFO,
                    message=f"Configured Hermes memory.provider at {config_path}.",
                )
            )

            bridge_path = _write_user_plugin_bridge(home)
            diagnostics.append(
                Diagnostic(
                    code="hermes.plugin.installed",
                    level=DiagnosticLevel.INFO,
                    message=f"Installed HM-Arch Hermes plugin bridge at {bridge_path}.",
                )
            )
            diagnostics.extend(_ensure_database_initialized(home))
        except ValueError as exc:
            diagnostics.append(
                Diagnostic(
                    code="hermes.install.failed",
                    level=DiagnosticLevel.ERROR,
                    message=str(exc),
                    remedy=f"Fix Hermes config.yaml syntax or permissions at {config_path}.",
                )
            )
            return IntegrationReport(
                agent=self.name,
                scope=None,
                state=IntegrationState.PARTIAL,
                config_root=home,
                diagnostics=tuple(diagnostics),
            )

        return IntegrationReport(
            agent=self.name,
            scope=None,
            state=IntegrationState.INSTALLED,
            config_root=home,
            installed_roles=("memory-provider",),
            diagnostics=tuple(diagnostics),
        )

    def uninstall(self, *, global_install: bool) -> IntegrationReport:
        del global_install
        home = resolve_hermes_home()
        config_path = home / "config.yaml"
        diagnostics = _base_diagnostics(home, config_path)
        changed = False
        preserved_db_path: str | None = None

        if config_path.exists():
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

            preserved_db_path = resolve_db_path(home, read_plugin_settings(config))
            changed = _remove_hm_arch_config(config) or changed
            if changed:
                _write_hermes_config(config_path, config)
                diagnostics.append(
                    Diagnostic(
                        code="hermes.config.updated",
                        level=DiagnosticLevel.INFO,
                        message=f"Removed HM-Arch Hermes config from {config_path}.",
                    )
                )
        else:
            diagnostics.append(
                Diagnostic(
                    code="hermes.config.missing",
                    level=DiagnosticLevel.INFO,
                    message=f"Hermes config file does not exist yet: {config_path}.",
                )
            )

        bridge_dir = _user_plugin_bridge_dir(home)
        if bridge_dir.exists():
            shutil.rmtree(bridge_dir)
            changed = True
            diagnostics.append(
                Diagnostic(
                    code="hermes.plugin.removed",
                    level=DiagnosticLevel.INFO,
                    message=f"Removed HM-Arch Hermes plugin bridge at {bridge_dir}.",
                )
            )
        else:
            diagnostics.append(
                Diagnostic(
                    code="hermes.plugin.not_present",
                    level=DiagnosticLevel.INFO,
                    message=f"HM-Arch Hermes plugin bridge is not present at {bridge_dir}.",
                )
            )

        db_path = preserved_db_path or str(home / DEFAULT_DB_FILENAME)
        if Path(db_path).exists():
            diagnostics.append(
                Diagnostic(
                    code="hermes.db.preserved",
                    level=DiagnosticLevel.INFO,
                    message=f"Preserved HM-Arch database at {db_path}.",
                    remedy="Delete this database manually only if you no longer need the memories.",
                )
            )

        state = IntegrationState.NOT_INSTALLED
        if not changed:
            diagnostics.append(
                Diagnostic(
                    code="hermes.uninstall.noop",
                    level=DiagnosticLevel.INFO,
                    message="Hermes HM-Arch integration was already not installed.",
                )
            )
        else:
            diagnostics.append(
                Diagnostic(
                    code="hermes.uninstalled",
                    level=DiagnosticLevel.INFO,
                    message="Removed Hermes HM-Arch integration. Restart Hermes if it is running.",
                )
            )

        return IntegrationReport(
            agent=self.name,
            scope=None,
            state=state,
            config_root=home,
            diagnostics=tuple(diagnostics),
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

        bridge_path = _user_plugin_bridge_path(home)
        if bridge_path.exists():
            diagnostics.append(
                Diagnostic(
                    code="hermes.plugin.bridge.present",
                    level=DiagnosticLevel.INFO,
                    message=f"Hermes HM-Arch plugin bridge exists at {bridge_path}.",
                )
            )
        elif provider == HM_ARCH_PROVIDER_NAME:
            state = IntegrationState.PARTIAL
            diagnostics.append(
                Diagnostic(
                    code="hermes.plugin.bridge.missing",
                    level=DiagnosticLevel.WARNING,
                    message=f"Hermes HM-Arch plugin bridge is missing at {bridge_path}.",
                    remedy="Run: hm-arch install hermes",
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
        else:
            if report.config_root is not None and not _user_plugin_bridge_path(
                report.config_root
            ).exists():
                bridge_path = _write_user_plugin_bridge(report.config_root)
                diagnostics.append(
                    Diagnostic(
                        code="hermes.plugin.installed",
                        level=DiagnosticLevel.INFO,
                        message=f"Installed HM-Arch Hermes plugin bridge at {bridge_path}.",
                    )
                )
            init_diagnostics = _ensure_database_initialized(report.config_root)
            if any(item.code == "hermes.db.created" for item in init_diagnostics):
                diagnostics = [
                    item for item in diagnostics if item.code != "hermes.db.missing"
                ]
            diagnostics.extend(init_diagnostics)
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


def _write_hermes_config(path: Path, config: dict[str, object]) -> None:
    try:
        import yaml
    except ImportError:
        text = _dump_minimal_yaml(config)
    else:
        text = yaml.safe_dump(config, default_flow_style=False, sort_keys=False)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _dump_minimal_yaml(config: dict[str, object], *, indent: int = 0) -> str:
    lines: list[str] = []
    prefix = " " * indent
    for key, value in config.items():
        if isinstance(value, dict):
            lines.append(f"{prefix}{key}:")
            lines.append(_dump_minimal_yaml(value, indent=indent + 2).rstrip())
        elif value is None:
            lines.append(f"{prefix}{key}: null")
        elif isinstance(value, bool):
            lines.append(f"{prefix}{key}: {'true' if value else 'false'}")
        else:
            rendered = str(value)
            if not rendered or any(char in rendered for char in ":#{}[]&,*?|-<>=!%@`"):
                rendered = repr(rendered)
            lines.append(f"{prefix}{key}: {rendered}")
    return "\n".join(lines) + "\n"


def _user_plugin_bridge_path(home: Path) -> Path:
    return _user_plugin_bridge_dir(home) / "__init__.py"


def _user_plugin_bridge_dir(home: Path) -> Path:
    return home / "plugins" / HM_ARCH_PROVIDER_NAME


def _write_user_plugin_bridge(home: Path) -> Path:
    plugin_dir = _user_plugin_bridge_dir(home)
    plugin_dir.mkdir(parents=True, exist_ok=True)
    bridge_path = plugin_dir / "__init__.py"
    bridge_path.write_text(
        '"""HM-Arch memory provider bridge for Hermes Agent."""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        "from hm_arch.integrations.hermes import HMArchHermesMemoryProvider\n"
        "\n"
        "\n"
        "def register(ctx):\n"
        '    """Register HM-Arch as the active Hermes memory provider."""\n'
        "    ctx.register_memory_provider(HMArchHermesMemoryProvider())\n",
        encoding="utf-8",
    )
    (plugin_dir / "plugin.yaml").write_text(
        "name: hm-arch\n"
        "description: HM-Arch local SQLite memory provider\n",
        encoding="utf-8",
    )
    return bridge_path


def _remove_hm_arch_config(config: dict[str, object]) -> bool:
    """Remove HM-Arch-owned Hermes config while preserving unrelated settings."""
    changed = False

    memory = config.get("memory")
    if isinstance(memory, dict) and memory.get("provider") == HM_ARCH_PROVIDER_NAME:
        del memory["provider"]
        changed = True
        if not memory:
            del config["memory"]
    elif config.get("memory.provider") == HM_ARCH_PROVIDER_NAME:
        del config["memory.provider"]
        changed = True

    plugins = config.get("plugins")
    if isinstance(plugins, dict) and HM_ARCH_PROVIDER_NAME in plugins:
        del plugins[HM_ARCH_PROVIDER_NAME]
        changed = True
        if not plugins:
            del config["plugins"]

    return changed


def _ensure_database_initialized(home: Path | None) -> list[Diagnostic]:
    """Create the configured Hermes HM-Arch database schema when missing."""
    if home is None:
        return []
    config_path = home / "config.yaml"
    try:
        config = load_hermes_config(config_path)
    except ValueError as exc:
        return [
            Diagnostic(
                code="hermes.config.invalid",
                level=DiagnosticLevel.ERROR,
                message=str(exc),
                remedy=f"Fix YAML syntax in {config_path}.",
            )
        ]

    db_path = resolve_db_path(home, read_plugin_settings(config))
    db_file = Path(db_path)
    existed = db_file.exists()
    try:
        if db_path != ":memory:":
            db_file.parent.mkdir(parents=True, exist_ok=True)
        with SQLiteStore(db_path) as store:
            store.initialize_schema()
    except Exception as exc:
        return [
            Diagnostic(
                code="hermes.db.init_failed",
                level=DiagnosticLevel.ERROR,
                message=f"Could not initialize HM-Arch database at {db_path}: {exc}",
                remedy=f"Check permissions for {db_file.parent}.",
            )
        ]

    if existed:
        message = f"HM-Arch database schema is initialized at {db_path}."
        code = "hermes.db.initialized"
    else:
        message = f"Created HM-Arch database at {db_path}."
        code = "hermes.db.created"
    return [
        Diagnostic(
            code=code,
            level=DiagnosticLevel.INFO,
            message=message,
        )
    ]
