"""Structured diagnostic logging for recovery workflows."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TextIO

from hm_arch.integrations.management.types import Diagnostic, DiagnosticLevel


class RecoveryPhase(str, Enum):
    """High-level recovery workflow identifier."""

    DOCTOR = "doctor"
    DOCTOR_FIX = "doctor_fix"
    BACKUP = "backup"
    RESTORE = "restore"
    REPAIR = "repair"


@dataclass(frozen=True)
class RecoveryLogEvent:
    """One structured recovery diagnostic event."""

    phase: str
    code: str
    level: str
    message: str
    remedy: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(tz=timezone.utc).isoformat(),
    )


class RecoveryLogger:
    """Emit JSON-line diagnostics for recovery commands."""

    def __init__(
        self,
        phase: RecoveryPhase,
        *,
        stream: TextIO | None = None,
        structured: bool = True,
    ) -> None:
        self.phase = phase
        self.stream = stream or sys.stderr
        self.structured = structured
        self.events: list[RecoveryLogEvent] = []

    def log(
        self,
        code: str,
        level: DiagnosticLevel,
        message: str,
        *,
        remedy: str | None = None,
        **details: Any,
    ) -> RecoveryLogEvent:
        event = RecoveryLogEvent(
            phase=self.phase.value,
            code=code,
            level=level.value,
            message=message,
            remedy=remedy,
            details=details,
        )
        self.events.append(event)
        if self.structured:
            print(json.dumps(asdict(event), sort_keys=True), file=self.stream)
        return event

    def log_diagnostic(self, diagnostic: Diagnostic, **details: Any) -> RecoveryLogEvent:
        return self.log(
            diagnostic.code,
            diagnostic.level,
            diagnostic.message,
            remedy=diagnostic.remedy,
            **details,
        )
