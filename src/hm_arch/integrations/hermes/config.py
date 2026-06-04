"""Hermes Agent configuration helpers for HM-Arch memory provider registration.

Detects an already configured external memory provider and refuses to silently
replace it when ``memory.provider`` points at another backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

HM_ARCH_PROVIDER_NAME = "hm-arch"
PLUGIN_CONFIG_SECTION = "hm-arch"
DEFAULT_DB_FILENAME = "hm_arch_memory.db"

_BUILTIN_PROVIDER_NAMES = frozenset({"builtin", "", None})


@dataclass(frozen=True)
class ExternalProviderConflict(Exception):
    """Raised when Hermes already has a different external memory provider."""

    configured_provider: str
    requested_provider: str = HM_ARCH_PROVIDER_NAME

    def __str__(self) -> str:
        return (
            f"Hermes memory.provider is already set to {self.configured_provider!r}; "
            f"refusing to silently replace it with {self.requested_provider!r}. "
            "Update memory.provider explicitly if you intend to switch providers."
        )


def _normalize_provider_name(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def read_memory_provider(config: Mapping[str, Any] | None) -> str | None:
    """Return the configured ``memory.provider`` value, if any."""
    if not config:
        return None
    memory = config.get("memory")
    if isinstance(memory, dict):
        return _normalize_provider_name(memory.get("provider"))
    return _normalize_provider_name(config.get("memory.provider"))


def detect_external_provider_conflict(
    config: Mapping[str, Any] | None,
    *,
    requested_provider: str = HM_ARCH_PROVIDER_NAME,
) -> ExternalProviderConflict | None:
    """Return a conflict when another external provider is already active."""
    configured = read_memory_provider(config)
    if configured is None or configured in _BUILTIN_PROVIDER_NAMES:
        return None
    if configured == requested_provider:
        return None
    return ExternalProviderConflict(
        configured_provider=configured,
        requested_provider=requested_provider,
    )


def assert_registration_allowed(
    config: Mapping[str, Any] | None,
    *,
    requested_provider: str = HM_ARCH_PROVIDER_NAME,
) -> None:
    """Raise :class:`ExternalProviderConflict` when registration must be refused."""
    conflict = detect_external_provider_conflict(
        config,
        requested_provider=requested_provider,
    )
    if conflict is not None:
        raise conflict


def read_plugin_settings(
    config: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return ``plugins.hm-arch`` settings from a Hermes config mapping."""
    if not config:
        return {}
    plugins = config.get("plugins")
    if not isinstance(plugins, dict):
        return {}
    section = plugins.get(PLUGIN_CONFIG_SECTION)
    if isinstance(section, dict):
        return dict(section)
    return {}


def resolve_db_path(
    hermes_home: str | Path,
    plugin_settings: Mapping[str, Any] | None = None,
) -> str:
    """Resolve the HM-Arch SQLite path under *hermes_home*."""
    home = Path(hermes_home).expanduser()
    settings = dict(plugin_settings or {})
    raw = settings.get("db_path")
    if isinstance(raw, str) and raw.strip():
        path = raw.strip()
        path = path.replace("$HERMES_HOME", str(home))
        path = path.replace("${HERMES_HOME}", str(home))
        return str(Path(path).expanduser())
    return str(home / DEFAULT_DB_FILENAME)


def _load_minimal_hermes_config(text: str) -> dict[str, Any]:
    """Parse a tiny YAML subset used by Hermes memory provider settings."""
    config: dict[str, Any] = {}
    memory: dict[str, Any] = {}
    plugins: dict[str, Any] = {}
    plugin_section: dict[str, Any] | None = None
    current_plugin: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped == "memory:":
            plugin_section = None
            current_plugin = None
            continue
        if stripped == "plugins:":
            plugin_section = plugins
            current_plugin = None
            continue

        if line.startswith("  ") and not line.startswith("    "):
            key, _, value = stripped.partition(":")
            value = value.strip().strip('"').strip("'")
            if plugin_section is None and key == "provider":
                memory["provider"] = value
                continue
            if plugin_section is not None and key.endswith(":"):
                current_plugin = key[:-1]
                plugin_section[current_plugin] = {}
                continue
            if plugin_section is not None and current_plugin:
                section = plugin_section.setdefault(current_plugin, {})
                if isinstance(section, dict):
                    section[key] = value
            continue

        if line.startswith("    ") and plugin_section is not None and current_plugin:
            key, _, value = stripped.partition(":")
            value = value.strip().strip('"').strip("'")
            section = plugin_section.setdefault(current_plugin, {})
            if isinstance(section, dict):
                section[key] = value

    if memory:
        config["memory"] = memory
    if plugins:
        config["plugins"] = plugins
    return config


def load_hermes_config(path: Path) -> dict[str, Any]:
    """Load a Hermes ``config.yaml`` document."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        return {}
    try:
        import yaml
    except ImportError:
        return _load_minimal_hermes_config(text)
    data = yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    return data


def merge_plugin_settings(
    config: dict[str, Any],
    values: Mapping[str, Any],
    *,
    provider_name: str = HM_ARCH_PROVIDER_NAME,
) -> dict[str, Any]:
    """Merge HM-Arch plugin settings without overwriting ``memory.provider``."""
    merged = dict(config)
    plugins = merged.setdefault("plugins", {})
    if not isinstance(plugins, dict):
        raise ValueError("config.plugins must be a mapping")
    section = plugins.setdefault(PLUGIN_CONFIG_SECTION, {})
    if not isinstance(section, dict):
        raise ValueError(f"config.plugins.{PLUGIN_CONFIG_SECTION} must be a mapping")
    section.update(dict(values))

    # Never mutate an unrelated external provider selection.
    existing = read_memory_provider(merged)
    if existing and existing not in _BUILTIN_PROVIDER_NAMES and existing != provider_name:
        return merged

    memory = merged.setdefault("memory", {})
    if not isinstance(memory, dict):
        raise ValueError("config.memory must be a mapping")
    if not _normalize_provider_name(memory.get("provider")):
        memory["provider"] = provider_name
    return merged
