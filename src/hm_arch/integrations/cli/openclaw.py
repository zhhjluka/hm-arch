"""``hm-arch openclaw`` CLI handlers."""

from __future__ import annotations

import argparse

from hm_arch.integrations.openclaw.sidecar import run_stdio_server


def add_openclaw_parsers(subparsers: argparse._SubParsersAction) -> None:
    openclaw_parser = subparsers.add_parser(
        "openclaw",
        help="OpenClaw integration commands.",
    )
    openclaw_sub = openclaw_parser.add_subparsers(dest="openclaw_command", required=True)
    openclaw_sub.add_parser(
        "sidecar",
        help="Run the persistent HM-Arch JSONL stdio sidecar server.",
    )


def run_openclaw_command(args: argparse.Namespace) -> int:
    if args.openclaw_command == "sidecar":
        return run_stdio_server()
    raise ValueError(f"unknown openclaw command {args.openclaw_command!r}")
