"""Resolve the packaged HM-Arch CLI executable for installed agent hooks."""

from __future__ import annotations

import os
import shutil
import sys

HM_ARCH_EXECUTABLE_ENV = "HM_ARCH_EXECUTABLE"


def resolve_hm_arch_command_prefix() -> tuple[str, ...]:
    """Return the command prefix that should invoke the HM-Arch CLI.

    Normal pip/pipx installs prefer ``hm-arch`` on PATH. PyInstaller standalone
    builds should invoke the frozen executable directly, not ``-m`` as though it
    were a Python interpreter. The environment variable is intentionally first
    so package managers can pin hooks to a managed runtime.
    """
    env_executable = os.environ.get(HM_ARCH_EXECUTABLE_ENV)
    if env_executable:
        return (env_executable,)

    executable = shutil.which("hm-arch")
    if executable:
        return (executable,)

    if getattr(sys, "frozen", False):
        return (sys.executable,)

    return (sys.executable, "-m", "hm_arch.integrations.cli")


def is_running_as_standalone() -> bool:
    """Return True when this process is the frozen HM-Arch standalone CLI."""
    return bool(getattr(sys, "frozen", False))
