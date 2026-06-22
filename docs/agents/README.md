# Agent installation guides

HM-Arch connects to coding agents through the packaged `hm-arch` CLI
and the coordinated Python/npm installer release line.

| Agent | Install hooks via CLI | Status / doctor |
|-------|----------------------|-----------------|
| [Codex](codex.md) | `hm-arch install codex` | `hm-arch status codex`, `hm-arch doctor codex` |
| [Claude Code](claude-code.md) | `hm-arch install claude-code` | `hm-arch status claude-code`, `hm-arch doctor claude-code` |
| [Hermes](hermes.md) | `hm-arch install hermes` | `hm-arch status hermes`, `hm-arch doctor hermes` |
| [OpenClaw](openclaw.md) | `hm-arch install openclaw` | `hm-arch status openclaw`, `hm-arch doctor openclaw` |

## Package install

| Channel | Command | When |
|---------|---------|------|
| GitHub Release wheel | `pip install /path/to/hm_arch-X.Y.Z-py3-none-any.whl` | v2.0.0+ |
| PyPI | `pip install hm-arch` or `pipx install hm-arch` | Latest stable release |
| npm | `npm install -g @hm-arch/installer` | Latest stable release |

The npm CLI is `hm-arch-install`. It installs Codex and Claude Code hooks, the
Hermes memory provider bridge (`hm-arch-install install hermes`), and the OpenClaw
memory plugin (`hm-arch-install install openclaw`). Restart Hermes or the OpenClaw
gateway after installation when those agents are already running, then validate
with `hm-arch-install status <agent>` and `hm-arch-install doctor <agent>`.

Clean-install verification for maintainers:
[pypi-clean-install.md](../pypi-clean-install.md).

Manual smoke tests for all agents:
[integration-cli-smoke.md](../integration-cli-smoke.md) (includes OpenClaw).

Release notes for the latest public release:
[RELEASE_NOTES_v2.0.4.md](../RELEASE_NOTES_v2.0.4.md).

OpenClaw integration readiness (unversioned validation findings):
[openclaw-release-readiness.md](../openclaw-release-readiness.md).

Memory export, import, migration, and sharing policies:
[memory-sharing-policies.md](../memory-sharing-policies.md).

Agent compatibility matrix (support and limitations):
[compatibility-matrix.md](compatibility-matrix.md).

Cross-agent benchmark matrix:
[benchmark-compatibility-matrix.md](benchmark-compatibility-matrix.md).
