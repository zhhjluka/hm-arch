"""Hermes Agent native Memory Provider integration for HM-Arch."""

from __future__ import annotations

from typing import Any

from .config import (
    DEFAULT_DB_FILENAME,
    HM_ARCH_PROVIDER_NAME,
    PLUGIN_CONFIG_SECTION,
    ExternalProviderConflict,
    assert_registration_allowed,
    detect_external_provider_conflict,
    load_hermes_config,
    merge_plugin_settings,
    read_memory_provider,
    read_plugin_settings,
    resolve_db_path,
)
from .provider import HMArchHermesMemoryProvider

__all__ = [
    "DEFAULT_DB_FILENAME",
    "HM_ARCH_PROVIDER_NAME",
    "PLUGIN_CONFIG_SECTION",
    "ExternalProviderConflict",
    "HMArchHermesMemoryProvider",
    "assert_registration_allowed",
    "detect_external_provider_conflict",
    "load_hermes_config",
    "merge_plugin_settings",
    "read_memory_provider",
    "read_plugin_settings",
    "register",
    "resolve_db_path",
]


def register(ctx: Any) -> None:
    """Hermes plugin entry point: register HM-Arch when config allows it."""
    hermes_home = getattr(ctx, "hermes_home", None)
    config: dict[str, Any] = {}
    if hermes_home:
        config_path = __import__("pathlib").Path(str(hermes_home)) / "config.yaml"
        if config_path.exists():
            config = load_hermes_config(config_path)
    assert_registration_allowed(config)
    ctx.register_memory_provider(HMArchHermesMemoryProvider())
