"""Shared types for integration management CLI."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol


class DiagnosticLevel(str, Enum):
    """Severity for integration diagnostics."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class IntegrationState(str, Enum):
    """High-level installation state for one agent and scope."""

    INSTALLED = "installed"
    PARTIAL = "partial"
    NOT_INSTALLED = "not_installed"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class Diagnostic:
    """One actionable integration diagnostic."""

    code: str
    level: DiagnosticLevel
    message: str
    remedy: str | None = None


@dataclass(frozen=True)
class IntegrationReport:
    """Status or doctor output for one agent integration."""

    agent: str
    scope: str | None
    state: IntegrationState
    config_root: Path | None = None
    installed_roles: tuple[str, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def has_errors(self) -> bool:
        return any(item.level == DiagnosticLevel.ERROR for item in self.diagnostics)


class AgentHandler(Protocol):
    """Per-agent integration management contract."""

    name: str
    supports_install: bool

    def install(self, *, global_install: bool) -> IntegrationReport: ...

    def uninstall(self, *, global_install: bool) -> IntegrationReport: ...

    def status(self, *, global_install: bool) -> IntegrationReport: ...

    def doctor(self, *, global_install: bool) -> IntegrationReport: ...
