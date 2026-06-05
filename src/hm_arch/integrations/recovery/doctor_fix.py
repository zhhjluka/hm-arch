"""Safe, non-destructive repairs for integration configuration issues."""

from __future__ import annotations

from dataclasses import dataclass, field

from hm_arch.integrations.claude_code.installer import (
    InstallScope as ClaudeInstallScope,
)
from hm_arch.integrations.claude_code.installer import install_claude_code
from hm_arch.integrations.codex.installer import InstallScope as CodexInstallScope
from hm_arch.integrations.codex.installer import install_codex
from hm_arch.integrations.management import get_agent_handler
from hm_arch.integrations.management.types import (
    Diagnostic,
    DiagnosticLevel,
    IntegrationReport,
    IntegrationState,
)

from .diagnostics import RecoveryLogger, RecoveryPhase

# Diagnostic codes that ``doctor --fix`` may repair automatically.
_CODEX_FIXABLE_CODES = frozenset(
    {
        "codex.hooks.incomplete",
        "codex.hooks.disabled",
        "codex.config.missing",
    }
)
_CLAUDE_FIXABLE_CODES = frozenset(
    {
        "claude_code.hooks.incomplete",
    }
)


@dataclass(frozen=True)
class FixAction:
    """One applied or skipped repair action."""

    agent: str
    code: str
    applied: bool
    message: str


@dataclass
class FixReport:
    """Summary of ``doctor --fix`` results."""

    actions: list[FixAction] = field(default_factory=list)

    @property
    def applied_count(self) -> int:
        return sum(1 for item in self.actions if item.applied)


def apply_safe_fixes(
    *,
    agent: str | None,
    global_install: bool,
    logger: RecoveryLogger | None = None,
) -> FixReport:
    """Apply safe repairs for supported agent integrations.

    Repairs are limited to re-installing Codex or Claude Code hooks when an
    installation is partial or misconfigured. Hermes conflicts, missing
    executables, and provider switches are never changed automatically.
    """
    log = logger or RecoveryLogger(RecoveryPhase.DOCTOR_FIX, structured=False)
    report = FixReport()

    agents = (agent,) if agent else ("codex", "claude-code")
    for name in agents:
        if name not in {"codex", "claude-code"}:
            continue
        before = get_agent_handler(name).doctor(global_install=global_install)
        actions = _fix_agent(name, before, global_install=global_install, logger=log)
        report.actions.extend(actions)

    return report


def _fix_agent(
    agent: str,
    before: IntegrationReport,
    *,
    global_install: bool,
    logger: RecoveryLogger,
) -> list[FixAction]:
    fixable_codes = (
        _CODEX_FIXABLE_CODES if agent == "codex" else _CLAUDE_FIXABLE_CODES
    )
    matching = [item for item in before.diagnostics if item.code in fixable_codes]
    if not matching:
        return []

    if before.state not in {IntegrationState.PARTIAL, IntegrationState.INSTALLED}:
        return [
            FixAction(
                agent=agent,
                code=item.code,
                applied=False,
                message=(
                    f"Skipped {item.code}: state is {before.state.value}; "
                    "run hm-arch install explicitly for a fresh install."
                ),
            )
            for item in matching
        ]

    if agent == "codex":
        scope = CodexInstallScope.GLOBAL if global_install else CodexInstallScope.PROJECT
        install_codex(scope)
    else:
        scope = (
            ClaudeInstallScope.GLOBAL if global_install else ClaudeInstallScope.PROJECT
        )
        install_claude_code(scope)

    after = get_agent_handler(agent).doctor(global_install=global_install)
    remaining_codes = {item.code for item in after.diagnostics if item.code in fixable_codes}
    actions: list[FixAction] = []
    for item in matching:
        applied = item.code not in remaining_codes
        message = (
            f"Re-installed {agent} hooks ({before.scope or 'project'})."
            if applied
            else f"Repair attempted for {item.code} but issue remains."
        )
        actions.append(
            FixAction(agent=agent, code=item.code, applied=applied, message=message)
        )
        logger.log(
            f"fix.{agent}.{item.code}",
            DiagnosticLevel.INFO if applied else DiagnosticLevel.WARNING,
            message,
            agent=agent,
            applied=applied,
        )
    return actions
