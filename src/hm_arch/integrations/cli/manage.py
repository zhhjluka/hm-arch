"""``hm-arch install``, ``uninstall``, ``status``, and ``doctor`` handlers."""

from __future__ import annotations

import argparse
import sys

from hm_arch.integrations.management import (
    ALL_AGENTS,
    get_agent_handler,
    list_agents,
)
from hm_arch.integrations.management.types import (
    DiagnosticLevel,
    IntegrationReport,
    IntegrationState,
)
from hm_arch.integrations.recovery.diagnostics import RecoveryLogger, RecoveryPhase
from hm_arch.integrations.recovery.doctor_fix import apply_safe_fixes
from hm_arch.integrations.recovery.database import storage_diagnostics


def add_manage_parsers(subparsers: argparse._SubParsersAction) -> None:
    install_parser = subparsers.add_parser(
        "install",
        help="Install HM-Arch integration hooks for a supported agent.",
    )
    install_parser.add_argument(
        "agent",
        choices=ALL_AGENTS,
        help="Agent integration to install (Hermes uses native plugin registration).",
    )
    install_parser.add_argument(
        "--global",
        dest="global_install",
        action="store_true",
        help="Install into the user-global agent configuration.",
    )

    uninstall_parser = subparsers.add_parser(
        "uninstall",
        help="Remove HM-Arch integration hooks for a supported agent.",
    )
    uninstall_parser.add_argument(
        "agent",
        choices=ALL_AGENTS,
        help="Agent integration to uninstall (Hermes config is edited manually).",
    )
    uninstall_parser.add_argument(
        "--global",
        dest="global_install",
        action="store_true",
        help="Uninstall from the user-global agent configuration.",
    )

    status_parser = subparsers.add_parser(
        "status",
        help="Show HM-Arch integration installation status.",
    )
    status_parser.add_argument(
        "agent",
        nargs="?",
        choices=ALL_AGENTS,
        help="Optional agent to inspect (default: all supported agents).",
    )
    status_parser.add_argument(
        "--global",
        dest="global_install",
        action="store_true",
        help="Inspect user-global agent configuration (Codex and Claude Code).",
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Run actionable diagnostics for HM-Arch agent integrations.",
    )
    doctor_parser.add_argument(
        "agent",
        nargs="?",
        choices=ALL_AGENTS,
        help="Optional agent to diagnose (default: all supported agents).",
    )
    doctor_parser.add_argument(
        "--global",
        dest="global_install",
        action="store_true",
        help="Diagnose user-global agent configuration (Codex and Claude Code).",
    )
    doctor_parser.add_argument(
        "--fix",
        action="store_true",
        help="Apply safe repairs for partial or misconfigured integrations.",
    )
    doctor_parser.add_argument(
        "--json",
        dest="structured_logs",
        action="store_true",
        help="Emit structured JSON diagnostic lines to stderr.",
    )


def _format_report(report: IntegrationReport) -> str:
    scope = f" ({report.scope})" if report.scope else ""
    lines = [
        f"{report.agent}{scope}: {report.state.value}",
    ]
    if report.config_root is not None:
        lines.append(f"  config: {report.config_root}")
    if report.installed_roles:
        lines.append(f"  roles: {', '.join(report.installed_roles)}")
    for item in report.diagnostics:
        prefix = item.level.value.upper()
        lines.append(f"  [{prefix}] {item.message}")
        if item.remedy:
            lines.append(f"         -> {item.remedy}")
    return "\n".join(lines)


def _print_report(report: IntegrationReport) -> None:
    print(_format_report(report), file=sys.stderr)


def _agents_for_args(agent: str | None) -> tuple[str, ...]:
    if agent:
        return (agent,)
    return list_agents()


def _print_codex_install_result(result: object) -> None:
    from hm_arch.integrations.codex.installer import InstallResult

    assert isinstance(result, InstallResult)
    print(
        f"Installed HM-Arch Codex hooks ({result.scope.value}) at {result.paths.root}",
        file=sys.stderr,
    )
    if result.hooks_json_changed:
        print(f"Updated {result.paths.hooks_json}", file=sys.stderr)
    if result.config_toml_changed:
        print(f"Enabled hooks in {result.paths.config_toml}", file=sys.stderr)


def _print_codex_uninstall_result(result: object) -> None:
    from hm_arch.integrations.codex.installer import InstallResult

    assert isinstance(result, InstallResult)
    print(
        f"Removed HM-Arch Codex hooks ({result.scope.value}) from {result.paths.root}",
        file=sys.stderr,
    )
    if result.hooks_json_changed and result.paths.hooks_json.exists():
        print(f"Updated {result.paths.hooks_json}", file=sys.stderr)
    elif result.hooks_json_changed:
        print(f"Removed {result.paths.hooks_json}", file=sys.stderr)


def _print_claude_install_result(result: object) -> None:
    from hm_arch.integrations.claude_code.installer import InstallResult

    assert isinstance(result, InstallResult)
    print(
        "Installed HM-Arch Claude Code hooks "
        f"({result.scope.value}) at {result.paths.root}",
        file=sys.stderr,
    )
    if result.settings_json_changed:
        print(f"Updated {result.paths.settings_json}", file=sys.stderr)


def _print_claude_uninstall_result(result: object) -> None:
    from hm_arch.integrations.claude_code.installer import InstallResult

    assert isinstance(result, InstallResult)
    print(
        "Removed HM-Arch Claude Code hooks "
        f"({result.scope.value}) from {result.paths.root}",
        file=sys.stderr,
    )
    if result.settings_json_changed and result.paths.settings_json.exists():
        print(f"Updated {result.paths.settings_json}", file=sys.stderr)
    elif result.settings_json_changed:
        print(f"Removed {result.paths.settings_json}", file=sys.stderr)


def run_install_command(args: argparse.Namespace) -> int:
    if args.agent == "codex":
        from hm_arch.integrations.codex.installer import InstallScope, install_codex

        scope = InstallScope.GLOBAL if args.global_install else InstallScope.PROJECT
        result = install_codex(scope)
        _print_codex_install_result(result)
        return 0

    if args.agent == "claude-code":
        from hm_arch.integrations.claude_code.installer import (
            InstallScope,
            install_claude_code,
        )

        scope = InstallScope.GLOBAL if args.global_install else InstallScope.PROJECT
        result = install_claude_code(scope)
        _print_claude_install_result(result)
        return 0

    handler = get_agent_handler(args.agent)
    report = handler.install(global_install=args.global_install)
    _print_report(report)
    return 2


def run_uninstall_command(args: argparse.Namespace) -> int:
    if args.agent == "codex":
        from hm_arch.integrations.codex.installer import InstallScope, uninstall_codex

        scope = InstallScope.GLOBAL if args.global_install else InstallScope.PROJECT
        result = uninstall_codex(scope)
        _print_codex_uninstall_result(result)
        return 0

    if args.agent == "claude-code":
        from hm_arch.integrations.claude_code.installer import (
            InstallScope,
            uninstall_claude_code,
        )

        scope = InstallScope.GLOBAL if args.global_install else InstallScope.PROJECT
        result = uninstall_claude_code(scope)
        _print_claude_uninstall_result(result)
        return 0

    handler = get_agent_handler(args.agent)
    report = handler.uninstall(global_install=args.global_install)
    _print_report(report)
    return 2


def run_status_command(args: argparse.Namespace) -> int:
    exit_code = 0
    for agent in _agents_for_args(args.agent):
        report = get_agent_handler(agent).status(
            global_install=args.global_install,
        )
        _print_report(report)
        if report.has_errors:
            exit_code = 1
    return exit_code


def run_doctor_command(args: argparse.Namespace) -> int:
    logger = RecoveryLogger(
        RecoveryPhase.DOCTOR_FIX if args.fix else RecoveryPhase.DOCTOR,
        structured=args.structured_logs,
    )
    exit_code = 0

    if args.fix:
        fix_report = apply_safe_fixes(
            agent=args.agent,
            global_install=args.global_install,
            logger=logger,
        )
        if fix_report.applied_count:
            print(
                f"Applied {fix_report.applied_count} safe repair(s).",
                file=sys.stderr,
            )

    for agent in _agents_for_args(args.agent):
        report = get_agent_handler(agent).doctor(
            global_install=args.global_install,
        )
        _print_report(report)
        for item in report.diagnostics:
            logger.log_diagnostic(item, agent=agent)
        if report.has_errors:
            exit_code = 1
        elif report.state in {
            IntegrationState.NOT_INSTALLED,
            IntegrationState.PARTIAL,
            IntegrationState.UNSUPPORTED,
        }:
            if any(
                item.level in {DiagnosticLevel.ERROR, DiagnosticLevel.WARNING}
                for item in report.diagnostics
            ):
                exit_code = 1

    if args.agent is None:
        storage_scope = "storage"
        print(f"{storage_scope}: diagnostics", file=sys.stderr)
        for item in storage_diagnostics():
            prefix = item.level.value.upper()
            print(f"  [{prefix}] {item.message}", file=sys.stderr)
            if item.remedy:
                print(f"         -> {item.remedy}", file=sys.stderr)
            logger.log_diagnostic(item, scope=storage_scope)
            if item.level == DiagnosticLevel.ERROR:
                exit_code = 1

    return exit_code
