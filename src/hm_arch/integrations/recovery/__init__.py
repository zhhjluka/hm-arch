"""Recovery diagnostics, doctor fixes, and database backup/restore/repair."""

from __future__ import annotations

from .database import (
    DatabaseRecoveryError,
    RepairReport,
    RestoreReport,
    backup_database,
    repair_database,
    restore_database,
    storage_diagnostics,
)
from .diagnostics import RecoveryLogger, RecoveryPhase
from .doctor_fix import FixReport, apply_safe_fixes

__all__ = [
    "DatabaseRecoveryError",
    "FixReport",
    "RecoveryLogger",
    "RecoveryPhase",
    "RepairReport",
    "RestoreReport",
    "apply_safe_fixes",
    "backup_database",
    "repair_database",
    "restore_database",
    "storage_diagnostics",
]
