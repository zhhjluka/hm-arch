"""``hm-arch install`` and ``hm-arch uninstall`` command handlers."""

from __future__ import annotations

import argparse
import sys

from hm_arch.integrations.codex.installer import InstallScope, install_codex, uninstall_codex

_SUPPORTED_AGENTS = ("codex",)


def add_install_parsers(subparsers: argparse._SubParsersAction) -> None:
    install_parser = subparsers.add_parser(
        "install",
        help="Install HM-Arch integration hooks for a supported agent.",
    )
    install_parser.add_argument(
        "agent",
        choices=_SUPPORTED_AGENTS,
        help="Agent integration to install.",
    )
    install_parser.add_argument(
        "--global",
        dest="global_install",
        action="store_true",
        help="Install into the user-global Codex configuration (~/.codex).",
    )

    uninstall_parser = subparsers.add_parser(
        "uninstall",
        help="Remove HM-Arch integration hooks for a supported agent.",
    )
    uninstall_parser.add_argument(
        "agent",
        choices=_SUPPORTED_AGENTS,
        help="Agent integration to uninstall.",
    )
    uninstall_parser.add_argument(
        "--global",
        dest="global_install",
        action="store_true",
        help="Uninstall from the user-global Codex configuration (~/.codex).",
    )


def run_install_command(args: argparse.Namespace) -> int:
    if args.agent != "codex":
        print(f"Unsupported agent: {args.agent}", file=sys.stderr)
        return 2

    scope = InstallScope.GLOBAL if args.global_install else InstallScope.PROJECT
    result = install_codex(scope)
    print(
        f"Installed HM-Arch Codex hooks ({scope.value}) at {result.paths.root}",
        file=sys.stderr,
    )
    if result.hooks_json_changed:
        print(f"Updated {result.paths.hooks_json}", file=sys.stderr)
    if result.config_toml_changed:
        print(f"Enabled hooks in {result.paths.config_toml}", file=sys.stderr)
    return 0


def run_uninstall_command(args: argparse.Namespace) -> int:
    if args.agent != "codex":
        print(f"Unsupported agent: {args.agent}", file=sys.stderr)
        return 2

    scope = InstallScope.GLOBAL if args.global_install else InstallScope.PROJECT
    result = uninstall_codex(scope)
    print(
        f"Removed HM-Arch Codex hooks ({scope.value}) from {result.paths.root}",
        file=sys.stderr,
    )
    if result.hooks_json_changed and result.paths.hooks_json.exists():
        print(f"Updated {result.paths.hooks_json}", file=sys.stderr)
    elif result.hooks_json_changed:
        print(f"Removed {result.paths.hooks_json}", file=sys.stderr)
    return 0
