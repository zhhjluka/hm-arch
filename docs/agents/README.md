# Agent installation guides

HM-Arch **v2.0.1** connects to coding agents through the packaged `hm-arch` CLI
and the coordinated Python/npm installer release line.

| Agent | Install hooks via CLI | Status / doctor |
|-------|----------------------|-----------------|
| [Codex](codex.md) | `hm-arch install codex` | `hm-arch status codex`, `hm-arch doctor codex` |
| [Claude Code](claude-code.md) | `hm-arch install claude-code` | `hm-arch status claude-code`, `hm-arch doctor claude-code` |
| [Hermes](hermes.md) | `hm-arch install hermes` | `hm-arch status hermes`, `hm-arch doctor hermes` |

## Package install

| Channel | Command | When |
|---------|---------|------|
| GitHub Release wheel | `pip install /path/to/hm_arch-X.Y.Z-py3-none-any.whl` | v2.0.0+ |
| PyPI | `pip install hm-arch==2.0.1` or `pipx install hm-arch==2.0.1` | Published v2.0.1 |
| npm | `npm install -g @hm-arch/installer@2.0.1` | Published v2.0.1 |

The npm CLI is `hm-arch-install`. It installs Codex and Claude Code hooks, and
installs the Hermes memory provider bridge with `hm-arch-install install hermes`.
Restart Hermes after installation, then validate with `hm-arch-install status hermes`
and `hm-arch-install doctor hermes`.

Clean-install verification for maintainers:
[pypi-clean-install.md](../pypi-clean-install.md).

Manual smoke tests for all three agents:
[integration-cli-smoke.md](../integration-cli-smoke.md).

Release notes for the latest patch release:
[RELEASE_NOTES_v2.0.1.md](../RELEASE_NOTES_v2.0.1.md).

Memory export, import, migration, and sharing policies:
[memory-sharing-policies.md](../memory-sharing-policies.md).

Agent compatibility matrix (support and limitations):
[compatibility-matrix.md](compatibility-matrix.md).
