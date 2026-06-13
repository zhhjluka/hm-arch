# Agent installation guides

HM-Arch **v2.0.0** connects to coding agents through the packaged `hm-arch` CLI
and the coordinated Python/npm installer release line.

| Agent | Install hooks via CLI | Status / doctor |
|-------|----------------------|-----------------|
| [Codex](codex.md) | `hm-arch install codex` | `hm-arch status codex`, `hm-arch doctor codex` |
| [Claude Code](claude-code.md) | `hm-arch install claude-code` | `hm-arch status claude-code`, `hm-arch doctor claude-code` |
| [Hermes](hermes.md) | Manual `config.yaml` + plugin (no `install hermes`) | `hm-arch status hermes`, `hm-arch doctor hermes` |

## Package install

| Channel | Command | When |
|---------|---------|------|
| GitHub Release wheel | `pip install /path/to/hm_arch-X.Y.Z-py3-none-any.whl` | v2.0.0+ |
| PyPI | `pip install hm-arch==2.0.0` or `pipx install hm-arch==2.0.0` | Published v2.0.0 |
| npm | `npm install -g @hm-arch/installer@2.0.0` | Published v2.0.0 |

The npm CLI is `hm-arch-install`. It installs Codex and Claude Code hooks, and it
checks Hermes configuration with `hm-arch-install status hermes` and
`hm-arch-install doctor hermes`. Hermes does not support `install hermes`;
configure `$HERMES_HOME/config.yaml` manually. While this repository is private,
use `HM_ARCH_RUNTIME=python` for npm-based Hermes checks so the installer uses
PyPI instead of private GitHub Release assets.

Clean-install verification for maintainers:
[pypi-clean-install.md](../pypi-clean-install.md).

Manual smoke tests for all three agents:
[integration-cli-smoke.md](../integration-cli-smoke.md).

Release notes for the coordinated v2 release:
[RELEASE_NOTES_v2.0.0.md](../RELEASE_NOTES_v2.0.0.md).

Memory export, import, migration, and sharing policies:
[memory-sharing-policies.md](../memory-sharing-policies.md).

Agent compatibility matrix (support and limitations):
[compatibility-matrix.md](compatibility-matrix.md).
