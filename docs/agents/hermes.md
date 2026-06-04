# Hermes Agent setup (HM-Arch)

Install HM-Arch and configure Hermes to use the native HM-Arch Memory Provider.
Hermes integration is **configuration-driven**: `hm-arch install hermes` and
`hm-arch uninstall hermes` are **not supported**. Use `hm-arch status hermes` and
`hm-arch doctor hermes` to inspect and diagnose configuration.

## Install HM-Arch

**From a GitHub Release wheel** (current v1.0.0):

```bash
python3.12 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install /path/to/hm_arch-1.0.0-py3-none-any.whl
```

**After maintainer-approved PyPI publish** (planned v1.1.0+):

```bash
pip install hm-arch
# or:
pipx install hm-arch
```

## Hermes home

Hermes reads configuration from:

- `$HERMES_HOME/config.yaml` when `HERMES_HOME` is set, or
- `~/.hermes/config.yaml` by default

```bash
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
mkdir -p "$HERMES_HOME"
```

## Configure HM-Arch (manual)

Edit `$HERMES_HOME/config.yaml`. Example minimal configuration:

```yaml
memory:
  provider: hm-arch
plugins:
  hm-arch:
    db_path: hm_arch_memory.db
```

- `memory.provider: hm-arch` selects the HM-Arch Memory Provider.
- `plugins.hm-arch.db_path` is relative to `HERMES_HOME` unless you use an
  absolute path. Default database file: `hm_arch_memory.db` under Hermes home.

Enable the HM-Arch plugin in Hermes Agent per Hermes documentation (plugin
discovery uses the installed `hm_arch` package and
`hm_arch.integrations.hermes.register`).

### Provider conflicts

If another external provider is already configured (e.g. `mem0`), HM-Arch refuses
to register silently. Set `memory.provider` to `hm-arch` **explicitly** when you
intend to switch.

## Smoke test (status and doctor only)

```bash
hm-arch status hermes
hm-arch doctor hermes
```

Expected when fully configured:

- `status` reports `installed` with role `memory-provider`
- `doctor` exits 0

Inspect all agents at once:

```bash
hm-arch status
hm-arch doctor
```

### Unsupported management commands

```bash
hm-arch install hermes    # exits 2 — use Hermes config + plugin registration
hm-arch uninstall hermes  # exits 2 — edit config.yaml manually
```

Diagnostics include remediation text pointing to `status` and `doctor`.

## Uninstall / disable

1. Stop using HM-Arch as the active provider in Hermes (edit `config.yaml`).
2. Remove or clear `plugins.hm-arch` settings without changing unrelated memory
   providers.
3. Optionally delete the SQLite database file if you no longer need stored
   memories.

Verify:

```bash
hm-arch status hermes
```

## Database path

Default: `$HERMES_HOME/hm_arch_memory.db`. Override with `plugins.hm-arch.db_path`
(supports `$HERMES_HOME` substitution in the path string).

## Related docs

- [Codex setup](codex.md)
- [Claude Code setup](claude-code.md)
- [Integration CLI smoke tests](../integration-cli-smoke.md)
- [PyPI clean-install verification](../pypi-clean-install.md)
