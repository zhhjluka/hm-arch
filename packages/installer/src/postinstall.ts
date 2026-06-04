/**
 * npm postinstall hook — intentionally a no-op.
 *
 * Agent configuration must only change after an explicit
 * ``hm-arch-install install`` command (see agent-integration-roadmap).
 */
export function postinstall(): void {
  // Deliberately empty: do not modify Codex, Claude Code, Hermes, or other agent config.
}

if (import.meta.main) {
  postinstall();
}
