# Claude Code setup (HM-Arch)

Install HM-Arch, wire Claude Code lifecycle hooks, smoke-test, and uninstall. All
steps are offline and do not require API keys.

## Install HM-Arch

**From a GitHub Release wheel** (current v2.0.4):

```bash
python3.12 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install /path/to/hm_arch-2.0.4-py3-none-any.whl
```

**From PyPI**:

```bash
pip install hm-arch
# or:
pipx install hm-arch
```

**From npm**:

```bash
npm install -g @hm-arch/installer
hm-arch-install install claude-code
```

Confirm the CLI:

```bash
hm-arch --help
# or, after npm install:
hm-arch-install --help
```

## Connect Claude Code (project scope)

Run from your project root (where you want `.claude/`):

```bash
cd /path/to/your/project
hm-arch install claude-code
```

This creates or updates `.claude/settings.json` with three HM-Arch hooks:

| Role | Event | Command |
|------|-------|---------|
| recall | `UserPromptSubmit` | `hm-arch claude-code recall` |
| record | `Stop` | `hm-arch claude-code record` |
| consolidate | `TeammateIdle` | `hm-arch claude-code consolidate` |

If `hm-arch` is not on `PATH`, the installer falls back to
`python -m hm_arch.integrations.cli claude-code …`.

### Global installation

```bash
hm-arch install claude-code --global
hm-arch status claude-code --global
hm-arch uninstall claude-code --global
```

## Smoke test

```bash
cd /path/to/your/project
hm-arch status claude-code
hm-arch doctor claude-code
```

Expected when installed:

- `status` reports `installed` with roles `recall`, `record`, `consolidate`
- `doctor` exits 0 when hooks are present and valid

Optional lifecycle check:

```bash
mkdir -p /tmp/hm-arch-claude-smoke && cd /tmp/hm-arch-claude-smoke
rm -rf .claude
hm-arch install claude-code && hm-arch status claude-code && hm-arch doctor claude-code
hm-arch uninstall claude-code
```

## Uninstall

```bash
cd /path/to/your/project
hm-arch uninstall claude-code
```

Only HM-Arch-owned hooks are removed from `.claude/settings.json`; your own hooks
are preserved.

## Database path

Set `HM_ARCH_DB_PATH` for a custom SQLite file, or omit it for
`./.hm_arch_agent_memory.db` in the Claude Code working directory.

## Manual / example hooks

Example scripts under `examples/claude_code_hooks/`. See
[examples/claude_code_hooks/README.md](../../examples/claude_code_hooks/README.md).

## Related docs

- [Codex setup](codex.md)
- [Hermes setup](hermes.md)
- [Integration CLI smoke tests](../integration-cli-smoke.md)
- [PyPI clean-install verification](../pypi-clean-install.md)
