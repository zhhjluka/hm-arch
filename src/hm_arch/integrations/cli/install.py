"""Backward-compatible re-exports for install CLI handlers."""

from __future__ import annotations

from .manage import (
    add_manage_parsers as add_install_parsers,
    run_install_command,
    run_uninstall_command,
)

__all__ = [
    "add_install_parsers",
    "run_install_command",
    "run_uninstall_command",
]
