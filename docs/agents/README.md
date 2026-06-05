# Agent installation guides

HM-Arch **v1.1.0** (Python-first three-agent integration) connects to coding agents
through the packaged `hm-arch` CLI.

| Agent | Install hooks via CLI | Status / doctor |
|-------|----------------------|-----------------|
| [Codex](codex.md) | `hm-arch install codex` | `hm-arch status codex`, `hm-arch doctor codex` |
| [Claude Code](claude-code.md) | `hm-arch install claude-code` | `hm-arch status claude-code`, `hm-arch doctor claude-code` |
| [Hermes](hermes.md) | Manual `config.yaml` + plugin (no `install hermes`) | `hm-arch status hermes`, `hm-arch doctor hermes` |

## Package install

| Channel | Command | When |
|---------|---------|------|
| GitHub Release wheel | `pip install /path/to/hm_arch-X.Y.Z-py3-none-any.whl` | v1.0.0+ (today) |
| PyPI | `pip install hm-arch` or `pipx install hm-arch` | After maintainer-approved publish (v1.1.0+) |

Clean-install verification for maintainers:
[pypi-clean-install.md](../pypi-clean-install.md).

Manual smoke tests for all three agents:
[integration-cli-smoke.md](../integration-cli-smoke.md).

Release notes for the Python-first integration:
[RELEASE_NOTES_v1.1.0.md](../RELEASE_NOTES_v1.1.0.md).

Memory export, import, migration, and sharing policies:
[memory-sharing-policies.md](../memory-sharing-policies.md).
