"""OpenClaw integration diagnostics and HM-Arch memory plugin management."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from hm_arch.integrations.openclaw.config import (
    DEFAULT_DB_FILENAME,
    HM_ARCH_PLUGIN_ID,
    detect_memory_slot_conflict,
    load_openclaw_config,
    merge_plugin_settings,
    read_memory_slot,
    read_plugin_settings,
    resolve_db_path,
    resolve_openclaw_config_path,
    resolve_openclaw_config_root,
    resolve_openclaw_state_dir,
    resolve_sidecar_command,
    write_openclaw_config,
)
from hm_arch.storage.sqlite import SQLiteStore

from .types import Diagnostic, DiagnosticLevel, IntegrationReport, IntegrationState

_OPENCLAW_INSTALL_REMEDY = (
    "OpenClaw uses native memory plugin registration; configure "
    "plugins.slots.memory and plugins.entries.memory-hm-arch in openclaw.json. "
    "Run `hm-arch status openclaw` and `hm-arch doctor openclaw` to inspect "
    "configuration."
)
_GATEWAY_RESTART_REMEDY = "Restart the OpenClaw gateway if it is running."
_PLUGIN_RUNTIME_REMEDY = (
    "Install @hm-arch/openclaw-plugin when published, or wait for the HM-Arch "
    "OpenClaw runtime package to supply a loadable plugin entrypoint."
)
_PLUGIN_RUNTIME_STUB_MARKER = "HM-Arch OpenClaw plugin runtime is not installed"


class OpenClawAgentHandler:
    """Manage HM-Arch OpenClaw memory plugin integration."""

    name = "openclaw"
    supports_install = True

    def install(self, *, global_install: bool) -> IntegrationReport:
        config_path = resolve_openclaw_config_path(global_install=global_install)
        config_root = resolve_openclaw_config_root(global_install=global_install)
        scope = "global" if global_install else "project"
        diagnostics = _base_diagnostics(config_root, config_path, scope=scope)

        try:
            config = load_openclaw_config(config_path) if config_path.exists() else {}
            conflict = detect_memory_slot_conflict(config)
            if conflict is not None:
                diagnostics.append(
                    Diagnostic(
                        code="openclaw.slot.conflict",
                        level=DiagnosticLevel.ERROR,
                        message=str(conflict),
                        remedy=(
                            "Set plugins.slots.memory to 'memory-hm-arch' explicitly "
                            "in openclaw.json if you intend to switch memory providers."
                        ),
                    )
                )
                return IntegrationReport(
                    agent=self.name,
                    scope=scope,
                    state=IntegrationState.PARTIAL,
                    config_root=config_root,
                    diagnostics=tuple(diagnostics),
                )

            plugin_settings = read_plugin_settings(config)
            db_path_setting = plugin_settings.get("dbPath", DEFAULT_DB_FILENAME)
            sidecar_command = list(resolve_sidecar_command())
            merged = merge_plugin_settings(
                config,
                {
                    "dbPath": db_path_setting,
                    "sidecarCommand": sidecar_command,
                    "autoRecall": True,
                    "autoCapture": True,
                },
            )
            write_openclaw_config(config_path, merged)
            diagnostics.append(
                Diagnostic(
                    code="openclaw.config.updated",
                    level=DiagnosticLevel.INFO,
                    message=f"Configured OpenClaw memory slot at {config_path}.",
                )
            )

            plugin_settings = read_plugin_settings(merged)
            try:
                manifest_path = _write_plugin_extension(config_root)
            except OSError as exc:
                diagnostics.append(
                    Diagnostic(
                        code="openclaw.plugin.write_failed",
                        level=DiagnosticLevel.ERROR,
                        message=(
                            f"Could not write HM-Arch OpenClaw plugin at "
                            f"{_plugin_extension_dir(config_root)}: {exc}"
                        ),
                        remedy=f"Check permissions for {config_root}.",
                    )
                )
                return IntegrationReport(
                    agent=self.name,
                    scope=scope,
                    state=IntegrationState.PARTIAL,
                    config_root=config_root,
                    diagnostics=tuple(diagnostics),
                )

            diagnostics.append(
                Diagnostic(
                    code="openclaw.plugin.installed",
                    level=DiagnosticLevel.INFO,
                    message=f"Installed HM-Arch OpenClaw plugin at {manifest_path.parent}.",
                )
            )
            diagnostics.extend(
                _ensure_database_initialized(
                    config_path,
                    config_root=config_root,
                    plugin_settings=plugin_settings,
                )
            )
            diagnostics.append(
                Diagnostic(
                    code="openclaw.gateway.restart",
                    level=DiagnosticLevel.INFO,
                    message="OpenClaw gateway restart is required to load the memory plugin.",
                    remedy=_GATEWAY_RESTART_REMEDY,
                )
            )
            runtime_ready = _plugin_runtime_ready(manifest_path.parent)
            if not runtime_ready:
                diagnostics.append(
                    Diagnostic(
                        code="openclaw.plugin.runtime_stub",
                        level=DiagnosticLevel.WARNING,
                        message=(
                            "OpenClaw plugin manifest and config are installed, but the "
                            "plugin entrypoint is a management-stage stub and will not load "
                            "until the HM-Arch OpenClaw runtime is available."
                        ),
                        remedy=_PLUGIN_RUNTIME_REMEDY,
                    )
                )
        except OSError as exc:
            diagnostics.append(
                Diagnostic(
                    code="openclaw.install.failed",
                    level=DiagnosticLevel.ERROR,
                    message=f"Could not write OpenClaw config at {config_path}: {exc}",
                    remedy=f"Check permissions for {config_path.parent}.",
                )
            )
            return IntegrationReport(
                agent=self.name,
                scope=scope,
                state=IntegrationState.PARTIAL,
                config_root=config_root,
                diagnostics=tuple(diagnostics),
            )
        except (ValueError, json.JSONDecodeError) as exc:
            diagnostics.append(
                Diagnostic(
                    code="openclaw.install.failed",
                    level=DiagnosticLevel.ERROR,
                    message=str(exc),
                    remedy=f"Fix OpenClaw config syntax or permissions at {config_path}.",
                )
            )
            return IntegrationReport(
                agent=self.name,
                scope=scope,
                state=IntegrationState.PARTIAL,
                config_root=config_root,
                diagnostics=tuple(diagnostics),
            )

        runtime_ready = _plugin_runtime_ready(_plugin_extension_dir(config_root))
        state = (
            IntegrationState.INSTALLED
            if runtime_ready
            else IntegrationState.PARTIAL
        )
        return IntegrationReport(
            agent=self.name,
            scope=scope,
            state=state,
            config_root=config_root,
            installed_roles=("memory-plugin",),
            diagnostics=tuple(diagnostics),
        )

    def uninstall(self, *, global_install: bool) -> IntegrationReport:
        config_path = resolve_openclaw_config_path(global_install=global_install)
        config_root = resolve_openclaw_config_root(global_install=global_install)
        scope = "global" if global_install else "project"
        diagnostics = _base_diagnostics(config_root, config_path, scope=scope)
        changed = False
        preserved_db_path: str | None = None

        if config_path.exists():
            try:
                config = load_openclaw_config(config_path)
            except (ValueError, json.JSONDecodeError) as exc:
                diagnostics.append(
                    Diagnostic(
                        code="openclaw.config.invalid",
                        level=DiagnosticLevel.ERROR,
                        message=str(exc),
                        remedy=f"Fix JSON syntax in {config_path}.",
                    )
                )
                return IntegrationReport(
                    agent=self.name,
                    scope=scope,
                    state=IntegrationState.PARTIAL,
                    config_root=config_root,
                    diagnostics=tuple(diagnostics),
                )

            preserved_db_path = resolve_db_path(config_root, read_plugin_settings(config))
            changed = _remove_hm_arch_config(config) or changed
            if changed:
                write_openclaw_config(config_path, config)
                diagnostics.append(
                    Diagnostic(
                        code="openclaw.config.updated",
                        level=DiagnosticLevel.INFO,
                        message=f"Removed HM-Arch OpenClaw config from {config_path}.",
                    )
                )
        else:
            diagnostics.append(
                Diagnostic(
                    code="openclaw.config.missing",
                    level=DiagnosticLevel.INFO,
                    message=f"OpenClaw config file does not exist yet: {config_path}.",
                )
            )

        extension_dir = _plugin_extension_dir(config_root)
        if extension_dir.exists():
            shutil.rmtree(extension_dir)
            changed = True
            diagnostics.append(
                Diagnostic(
                    code="openclaw.plugin.removed",
                    level=DiagnosticLevel.INFO,
                    message=f"Removed HM-Arch OpenClaw plugin at {extension_dir}.",
                )
            )
        else:
            diagnostics.append(
                Diagnostic(
                    code="openclaw.plugin.not_present",
                    level=DiagnosticLevel.INFO,
                    message=f"HM-Arch OpenClaw plugin is not present at {extension_dir}.",
                )
            )

        db_path = preserved_db_path or str(config_root / DEFAULT_DB_FILENAME)
        if Path(db_path).exists():
            diagnostics.append(
                Diagnostic(
                    code="openclaw.db.preserved",
                    level=DiagnosticLevel.INFO,
                    message=f"Preserved HM-Arch database at {db_path}.",
                    remedy="Delete this database manually only if you no longer need the memories.",
                )
            )

        state = IntegrationState.NOT_INSTALLED
        if not changed:
            diagnostics.append(
                Diagnostic(
                    code="openclaw.uninstall.noop",
                    level=DiagnosticLevel.INFO,
                    message="OpenClaw HM-Arch integration was already not installed.",
                )
            )
        else:
            diagnostics.append(
                Diagnostic(
                    code="openclaw.uninstalled",
                    level=DiagnosticLevel.INFO,
                    message="Removed OpenClaw HM-Arch integration.",
                    remedy=_GATEWAY_RESTART_REMEDY,
                )
            )

        return IntegrationReport(
            agent=self.name,
            scope=scope,
            state=state,
            config_root=config_root,
            diagnostics=tuple(diagnostics),
        )

    def status(self, *, global_install: bool) -> IntegrationReport:
        config_path = resolve_openclaw_config_path(global_install=global_install)
        config_root = resolve_openclaw_config_root(global_install=global_install)
        scope = "global" if global_install else "project"
        diagnostics = _base_diagnostics(config_root, config_path, scope=scope)

        if not config_path.exists():
            return IntegrationReport(
                agent=self.name,
                scope=scope,
                state=IntegrationState.NOT_INSTALLED,
                config_root=config_root,
                diagnostics=tuple(diagnostics),
            )

        try:
            config = load_openclaw_config(config_path)
        except (ValueError, json.JSONDecodeError) as exc:
            diagnostics.append(
                Diagnostic(
                    code="openclaw.config.invalid",
                    level=DiagnosticLevel.ERROR,
                    message=str(exc),
                    remedy=f"Fix JSON syntax in {config_path}.",
                )
            )
            return IntegrationReport(
                agent=self.name,
                scope=scope,
                state=IntegrationState.PARTIAL,
                config_root=config_root,
                diagnostics=tuple(diagnostics),
            )

        slot = read_memory_slot(config)
        plugin_settings = read_plugin_settings(config)
        conflict = detect_memory_slot_conflict(config)

        if conflict is not None:
            diagnostics.append(
                Diagnostic(
                    code="openclaw.slot.conflict",
                    level=DiagnosticLevel.ERROR,
                    message=str(conflict),
                    remedy=(
                        "Set plugins.slots.memory to 'memory-hm-arch' explicitly "
                        "in openclaw.json if you intend to switch memory providers."
                    ),
                )
            )
            state = IntegrationState.PARTIAL
        elif slot == HM_ARCH_PLUGIN_ID:
            state = IntegrationState.INSTALLED
            diagnostics.append(
                Diagnostic(
                    code="openclaw.slot.active",
                    level=DiagnosticLevel.INFO,
                    message=f"OpenClaw plugins.slots.memory is set to {slot!r}.",
                )
            )
        elif slot in (None, "none"):
            state = IntegrationState.NOT_INSTALLED
            diagnostics.append(
                Diagnostic(
                    code="openclaw.slot.not_configured",
                    level=DiagnosticLevel.INFO,
                    message=(
                        "OpenClaw plugins.slots.memory is not set to memory-hm-arch; "
                        "plugin settings may still be present."
                    ),
                    remedy=_OPENCLAW_INSTALL_REMEDY,
                )
            )
        else:
            state = IntegrationState.PARTIAL
            diagnostics.append(
                Diagnostic(
                    code="openclaw.slot.other",
                    level=DiagnosticLevel.WARNING,
                    message=f"OpenClaw plugins.slots.memory is {slot!r}.",
                    remedy=_OPENCLAW_INSTALL_REMEDY,
                )
            )

        if plugin_settings:
            diagnostics.append(
                Diagnostic(
                    code="openclaw.plugin.configured",
                    level=DiagnosticLevel.INFO,
                    message=f"plugins.entries.memory-hm-arch settings found: {sorted(plugin_settings)}.",
                )
            )

        manifest_path = _plugin_manifest_path(config_root)
        if manifest_path.exists():
            diagnostics.append(
                Diagnostic(
                    code="openclaw.plugin.present",
                    level=DiagnosticLevel.INFO,
                    message=f"HM-Arch OpenClaw plugin manifest exists at {manifest_path}.",
                )
            )
            if slot == HM_ARCH_PLUGIN_ID and not _plugin_runtime_ready(manifest_path.parent):
                state = IntegrationState.PARTIAL
                diagnostics.append(
                    Diagnostic(
                        code="openclaw.plugin.runtime_stub",
                        level=DiagnosticLevel.WARNING,
                        message=(
                            "HM-Arch OpenClaw plugin entrypoint is a management-stage stub "
                            "and will not load until the runtime package is available."
                        ),
                        remedy=_PLUGIN_RUNTIME_REMEDY,
                    )
                )
        elif slot == HM_ARCH_PLUGIN_ID:
            state = IntegrationState.PARTIAL
            diagnostics.append(
                Diagnostic(
                    code="openclaw.plugin.missing",
                    level=DiagnosticLevel.WARNING,
                    message=f"HM-Arch OpenClaw plugin is missing at {manifest_path.parent}.",
                    remedy="Run: hm-arch install openclaw",
                )
            )

        diagnostics.extend(_sidecar_diagnostics(plugin_settings))
        db_path = resolve_db_path(config_root, plugin_settings)
        db_file = Path(db_path)
        if db_file.exists():
            diagnostics.append(
                Diagnostic(
                    code="openclaw.db.present",
                    level=DiagnosticLevel.INFO,
                    message=f"HM-Arch database exists at {db_path}.",
                )
            )
        else:
            diagnostics.append(
                Diagnostic(
                    code="openclaw.db.missing",
                    level=DiagnosticLevel.INFO,
                    message=f"HM-Arch database not created yet at {db_path}.",
                )
            )

        roles: tuple[str, ...] = ()
        if slot == HM_ARCH_PLUGIN_ID:
            roles = ("memory-plugin",)

        return IntegrationReport(
            agent=self.name,
            scope=scope,
            state=state,
            config_root=config_root,
            installed_roles=roles,
            diagnostics=tuple(diagnostics),
        )

    def doctor(self, *, global_install: bool) -> IntegrationReport:
        report = self.status(global_install=global_install)
        diagnostics = list(report.diagnostics)
        conflict_codes = {"openclaw.slot.conflict", "openclaw.config.invalid"}
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
                    code="openclaw.not_configured",
                    level=DiagnosticLevel.WARNING,
                    message=(
                        "OpenClaw is not fully configured to use HM-Arch as the active "
                        "memory plugin."
                    ),
                    remedy=_OPENCLAW_INSTALL_REMEDY,
                )
            )
        else:
            if report.config_root is not None and not _plugin_manifest_path(
                report.config_root
            ).exists():
                try:
                    manifest_path = _write_plugin_extension(report.config_root)
                except OSError as exc:
                    diagnostics.append(
                        Diagnostic(
                            code="openclaw.plugin.write_failed",
                            level=DiagnosticLevel.ERROR,
                            message=(
                                f"Could not write HM-Arch OpenClaw plugin at "
                                f"{_plugin_extension_dir(report.config_root)}: {exc}"
                            ),
                            remedy=f"Check permissions for {report.config_root}.",
                        )
                    )
                    return IntegrationReport(
                        agent=report.agent,
                        scope=report.scope,
                        state=IntegrationState.PARTIAL,
                        config_root=report.config_root,
                        installed_roles=report.installed_roles,
                        diagnostics=tuple(diagnostics),
                    )
                diagnostics.append(
                    Diagnostic(
                        code="openclaw.plugin.installed",
                        level=DiagnosticLevel.INFO,
                        message=f"Installed HM-Arch OpenClaw plugin at {manifest_path.parent}.",
                    )
                )
            config_path = resolve_openclaw_config_path(global_install=global_install)
            plugin_settings = (
                read_plugin_settings(load_openclaw_config(config_path))
                if config_path.exists()
                else {}
            )
            init_diagnostics = _ensure_database_initialized(
                config_path,
                config_root=report.config_root,
                plugin_settings=plugin_settings,
            )
            if any(item.code == "openclaw.db.created" for item in init_diagnostics):
                diagnostics = [
                    item for item in diagnostics if item.code != "openclaw.db.missing"
                ]
            diagnostics.extend(init_diagnostics)
            diagnostics.extend(_storage_permission_diagnostics(report.config_root))
        return IntegrationReport(
            agent=report.agent,
            scope=report.scope,
            state=report.state,
            config_root=report.config_root,
            installed_roles=report.installed_roles,
            diagnostics=tuple(diagnostics),
        )


def _base_diagnostics(
    config_root: Path,
    config_path: Path,
    *,
    scope: str,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    openclaw_cli = shutil.which("openclaw")
    if openclaw_cli:
        diagnostics.append(
            Diagnostic(
                code="openclaw.cli.found",
                level=DiagnosticLevel.INFO,
                message=f"openclaw CLI found at {openclaw_cli}.",
            )
        )
    else:
        diagnostics.append(
            Diagnostic(
                code="openclaw.cli.missing",
                level=DiagnosticLevel.WARNING,
                message="openclaw executable was not found on PATH.",
                remedy="Install OpenClaw CLI or verify OPENCLAW_STATE_DIR and PATH.",
            )
        )

    state_dir = resolve_openclaw_state_dir()
    diagnostics.append(
        Diagnostic(
            code="openclaw.home",
            level=DiagnosticLevel.INFO,
            message=(
                f"OpenClaw scope={scope}, config root: {config_root} "
                f"(config: {config_path}, state: {state_dir})."
            ),
        )
    )
    return diagnostics


def _plugin_entrypoint_path(plugin_dir: Path) -> Path:
    return plugin_dir / "index.mjs"


def _plugin_runtime_ready(plugin_dir: Path) -> bool:
    """Return True when the plugin entrypoint is loadable (not a management stub)."""
    package_json = plugin_dir / "package.json"
    if package_json.exists():
        try:
            payload = json.loads(package_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        extensions = payload.get("openclaw", {}).get("extensions", [])
        if isinstance(extensions, list):
            for entry in extensions:
                if not isinstance(entry, str):
                    continue
                candidate = plugin_dir / entry.removeprefix("./")
                if candidate.exists() and _PLUGIN_RUNTIME_STUB_MARKER not in candidate.read_text(
                    encoding="utf-8"
                ):
                    return True
    entrypoint = _plugin_entrypoint_path(plugin_dir)
    if not entrypoint.exists():
        return False
    try:
        text = entrypoint.read_text(encoding="utf-8")
    except OSError:
        return False
    return _PLUGIN_RUNTIME_STUB_MARKER not in text


def _plugin_extension_dir(config_root: Path) -> Path:
    return config_root / "extensions" / HM_ARCH_PLUGIN_ID


def _plugin_manifest_path(config_root: Path) -> Path:
    return _plugin_extension_dir(config_root) / "openclaw.plugin.json"


def _plugin_source_dir() -> Path | None:
    """Return the repository-local OpenClaw plugin package when available."""
    repo_root = Path(__file__).resolve().parents[4]
    candidate = repo_root / "packages" / "openclaw-plugin"
    dist_entry = candidate / "dist" / "index.js"
    manifest = candidate / "openclaw.plugin.json"
    if dist_entry.exists() and manifest.exists():
        return candidate
    return None


def _copy_plugin_runtime(plugin_dir: Path, source_dir: Path) -> None:
    """Copy the built HM-Arch OpenClaw plugin runtime into an extension directory."""
    shutil.copy2(source_dir / "openclaw.plugin.json", plugin_dir / "openclaw.plugin.json")
    package_json = source_dir / "package.json"
    if package_json.exists():
        shutil.copy2(package_json, plugin_dir / "package.json")
    dist_src = source_dir / "dist"
    dist_dest = plugin_dir / "dist"
    if dist_dest.exists():
        shutil.rmtree(dist_dest)
    shutil.copytree(dist_src, dist_dest)
    legacy_entry = plugin_dir / "index.mjs"
    if legacy_entry.exists():
        legacy_entry.unlink()


def _write_plugin_stub(plugin_dir: Path) -> None:
    manifest_path = plugin_dir / "openclaw.plugin.json"
    manifest_path.write_text(
        json.dumps(
            {
                "id": HM_ARCH_PLUGIN_ID,
                "name": "HM-Arch Memory",
                "description": "HM-Arch local SQLite memory provider for OpenClaw",
                "kind": "memory",
                "version": "0.0.0",
                "configSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "dbPath": {"type": "string"},
                        "sidecarCommand": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "autoRecall": {"type": "boolean"},
                        "autoCapture": {"type": "boolean"},
                        "topK": {"type": "integer"},
                        "maxContextChars": {"type": "integer"},
                        "consolidateOnSessionEnd": {"type": "boolean"},
                    },
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (plugin_dir / "package.json").write_text(
        json.dumps(
            {
                "name": "@hm-arch/openclaw-memory",
                "version": "0.0.0",
                "private": True,
                "type": "module",
                "openclaw": {"extensions": ["./index.mjs"]},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (plugin_dir / "index.mjs").write_text(
        "// HM-Arch OpenClaw memory plugin entrypoint.\n"
        "// Full runtime is provided by @hm-arch/openclaw-plugin when published.\n"
        "export async function register() {\n"
        f"  throw new Error('{_PLUGIN_RUNTIME_STUB_MARKER}. "
        "Install @hm-arch/openclaw-plugin or run hm-arch install openclaw.');\n"
        "}\n",
        encoding="utf-8",
    )


def _write_plugin_extension(config_root: Path) -> Path:
    plugin_dir = _plugin_extension_dir(config_root)
    plugin_dir.mkdir(parents=True, exist_ok=True)
    source_dir = _plugin_source_dir()
    if source_dir is not None:
        _copy_plugin_runtime(plugin_dir, source_dir)
    else:
        _write_plugin_stub(plugin_dir)
    return plugin_dir / "openclaw.plugin.json"


def _remove_hm_arch_config(config: dict[str, object]) -> bool:
    """Remove HM-Arch-owned OpenClaw config while preserving unrelated settings."""
    changed = False
    plugins = config.get("plugins")
    if not isinstance(plugins, dict):
        return False

    entries = plugins.get("entries")
    if isinstance(entries, dict) and HM_ARCH_PLUGIN_ID in entries:
        del entries[HM_ARCH_PLUGIN_ID]
        changed = True
        if not entries:
            del plugins["entries"]

    slots = plugins.get("slots")
    if isinstance(slots, dict) and slots.get("memory") == HM_ARCH_PLUGIN_ID:
        slots["memory"] = "none"
        changed = True

    if isinstance(plugins, dict) and not plugins:
        del config["plugins"]
        changed = True

    return changed


def _sidecar_diagnostics(plugin_settings: dict[str, object]) -> list[Diagnostic]:
    configured = plugin_settings.get("sidecarCommand")
    command = (
        tuple(str(part) for part in configured)
        if isinstance(configured, list) and configured
        else resolve_sidecar_command()
    )
    executable = command[0]
    if os.path.isabs(executable):
        found = Path(executable).exists()
    else:
        found = shutil.which(executable) is not None

    diagnostics: list[Diagnostic] = [
        Diagnostic(
            code="openclaw.sidecar.command",
            level=DiagnosticLevel.INFO,
            message=f"Configured HM-Arch sidecar command: {' '.join(command)}.",
        )
    ]
    if found:
        diagnostics.append(
            Diagnostic(
                code="openclaw.sidecar.executable",
                level=DiagnosticLevel.INFO,
                message=f"Sidecar executable prefix found: {executable!r}.",
            )
        )
    else:
        diagnostics.append(
            Diagnostic(
                code="openclaw.sidecar.missing",
                level=DiagnosticLevel.WARNING,
                message=f"Sidecar executable prefix not found: {executable!r}.",
                remedy="Install hm-arch on PATH or set HM_ARCH_EXECUTABLE.",
            )
        )
    return diagnostics


def _storage_permission_diagnostics(config_root: Path | None) -> list[Diagnostic]:
    if config_root is None:
        return []
    try:
        config_root.mkdir(parents=True, exist_ok=True)
        probe = config_root / ".hm_arch_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return [
            Diagnostic(
                code="openclaw.storage.permission_denied",
                level=DiagnosticLevel.ERROR,
                message=f"Cannot write to OpenClaw config root {config_root}: {exc}",
                remedy=f"Check permissions for {config_root}.",
            )
        ]
    return [
        Diagnostic(
            code="openclaw.storage.writable",
            level=DiagnosticLevel.INFO,
            message=f"OpenClaw config root is writable: {config_root}.",
        )
    ]


def _ensure_database_initialized(
    config_path: Path | None,
    *,
    config_root: Path | None = None,
    plugin_settings: dict[str, object] | None = None,
) -> list[Diagnostic]:
    if config_path is None:
        return []
    root = config_root or config_path.parent
    settings = plugin_settings
    if settings is None:
        try:
            config = load_openclaw_config(config_path) if config_path.exists() else {}
        except (ValueError, json.JSONDecodeError) as exc:
            return [
                Diagnostic(
                    code="openclaw.config.invalid",
                    level=DiagnosticLevel.ERROR,
                    message=str(exc),
                    remedy=f"Fix JSON syntax in {config_path}.",
                )
            ]
        settings = read_plugin_settings(config)

    db_path = resolve_db_path(root, settings)
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
                code="openclaw.db.init_failed",
                level=DiagnosticLevel.ERROR,
                message=f"Could not initialize HM-Arch database at {db_path}: {exc}",
                remedy=f"Check permissions for {db_file.parent}.",
            )
        ]

    if existed:
        message = f"HM-Arch database schema is initialized at {db_path}."
        code = "openclaw.db.initialized"
    else:
        message = f"Created HM-Arch database at {db_path}."
        code = "openclaw.db.created"
    return [
        Diagnostic(
            code=code,
            level=DiagnosticLevel.INFO,
            message=message,
        )
    ]
