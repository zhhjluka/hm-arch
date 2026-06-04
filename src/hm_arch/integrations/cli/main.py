"""``hm-arch`` console entry point for adapter runtime commands."""

from __future__ import annotations

import argparse
import json
import sys

from hm_arch.integrations.protocol import AdapterOperation

from .io import emit_adapter_response, read_adapter_payload
from .runtime import _fail_open_for_operation, dispatch_adapter_request

_SUPPORTED_COMMANDS = tuple(op.value for op in AdapterOperation)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hm-arch",
        description="HM-Arch adapter runtime: recall, record, and consolidate.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in _SUPPORTED_COMMANDS:
        subparsers.add_parser(
            command,
            help=f"Run the {command} adapter operation (JSON request on stdin).",
        )
    return parser


def run_command(command: str) -> int:
    """Execute one adapter command and emit JSON to stdout."""
    try:
        payload = read_adapter_payload()
    except json.JSONDecodeError as exc:
        response = _fail_open_for_operation(command, f"invalid JSON on stdin: {exc}")
        emit_adapter_response(response)
        return 0

    response = dispatch_adapter_request(command, payload)
    emit_adapter_response(response)
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``hm-arch recall|record|consolidate``."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    return run_command(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
