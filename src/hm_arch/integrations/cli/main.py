"""``hm-arch`` console entry point for adapter runtime commands."""

from __future__ import annotations

import argparse
import json
import sys

from hm_arch.integrations.protocol import AdapterOperation

from .manage import (
    add_manage_parsers,
    run_doctor_command,
    run_install_command,
    run_status_command,
    run_uninstall_command,
)
from .io import (
    InvalidAdapterPayloadError,
    emit_adapter_response,
    read_adapter_payload,
)
from .runtime import _fail_open_for_operation, dispatch_adapter_request

_SUPPORTED_COMMANDS = tuple(op.value for op in AdapterOperation)
_CODEX_BRIDGE_COMMANDS = {
    "recall": "run_codex_recall",
    "record": "run_codex_record",
    "consolidate": "run_codex_consolidate",
}
_CLAUDE_CODE_BRIDGE_COMMANDS = {
    "recall": "run_claude_recall",
    "record": "run_claude_record",
    "consolidate": "run_claude_consolidate",
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hm-arch",
        description="HM-Arch adapter runtime: recall, record, consolidate, and agent install.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in _SUPPORTED_COMMANDS:
        subparsers.add_parser(
            command,
            help=f"Run the {command} adapter operation (JSON request on stdin).",
        )

    codex_parser = subparsers.add_parser(
        "codex",
        help="Run Codex lifecycle hook bridges (JSON on stdin, Codex JSON on stdout).",
    )
    codex_subparsers = codex_parser.add_subparsers(dest="codex_command", required=True)
    for name, help_text in (
        ("recall", "Codex UserPromptSubmit recall hook."),
        ("record", "Codex Stop turn recording hook."),
        ("consolidate", "Codex Stop idle consolidation hook."),
    ):
        codex_subparsers.add_parser(name, help=help_text)

    claude_parser = subparsers.add_parser(
        "claude-code",
        help="Run Claude Code lifecycle hook bridges (JSON on stdin).",
    )
    claude_subparsers = claude_parser.add_subparsers(
        dest="claude_code_command",
        required=True,
    )
    for name, help_text in (
        ("recall", "Claude Code UserPromptSubmit recall hook."),
        ("record", "Claude Code Stop turn recording hook."),
        ("consolidate", "Claude Code TeammateIdle consolidation hook."),
    ):
        claude_subparsers.add_parser(name, help=help_text)

    add_manage_parsers(subparsers)
    return parser


def run_command(command: str) -> int:
    """Execute one adapter command and emit JSON to stdout."""
    try:
        payload = read_adapter_payload()
    except json.JSONDecodeError as exc:
        response = _fail_open_for_operation(command, f"invalid JSON on stdin: {exc}")
        emit_adapter_response(response)
        return 0
    except InvalidAdapterPayloadError as exc:
        response = _fail_open_for_operation(command, str(exc))
        emit_adapter_response(response)
        return 0

    response = dispatch_adapter_request(command, payload)
    emit_adapter_response(response)
    return 0


def run_codex_bridge(command: str) -> int:
    from hm_arch.integrations.codex import bridge

    handler_name = _CODEX_BRIDGE_COMMANDS[command]
    handler = getattr(bridge, handler_name)
    return handler()


def run_claude_code_bridge(command: str) -> int:
    from hm_arch.integrations.claude_code import bridge

    handler_name = _CLAUDE_CODE_BRIDGE_COMMANDS[command]
    handler = getattr(bridge, handler_name)
    return handler()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``hm-arch``."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command in _SUPPORTED_COMMANDS:
        return run_command(args.command)
    if args.command == "codex":
        return run_codex_bridge(args.codex_command)
    if args.command == "claude-code":
        return run_claude_code_bridge(args.claude_code_command)
    if args.command == "install":
        return run_install_command(args)
    if args.command == "uninstall":
        return run_uninstall_command(args)
    if args.command == "status":
        return run_status_command(args)
    if args.command == "doctor":
        return run_doctor_command(args)

    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
