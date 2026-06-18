"""CLI entry for ``hm-arch openclaw sidecar``."""

from __future__ import annotations

from .server import SidecarServer, configure_sidecar_logging


def run_openclaw_sidecar() -> int:
    """Start the persistent JSONL stdio sidecar process."""
    configure_sidecar_logging()
    return SidecarServer().run()
