# Hermes Agent setup (HM-Arch)

Install HM-Arch and configure Hermes to use the native HM-Arch Memory Provider.
Hermes integration uses native plugin registration. `hm-arch install hermes`
creates the HM-Arch plugin bridge, updates `$HERMES_HOME/config.yaml`, and
initializes the SQLite database.

## Install HM-Arch

**From a GitHub Release wheel** (current v2.0.1):

```bash
python3.12 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install /path/to/hm_arch-2.0.1-py3-none-any.whl
```

**From PyPI**:

```bash
pip install hm-arch==2.0.1
# or:
pipx install hm-arch==2.0.1
```

**From npm**:

```bash
npm install -g @hm-arch/installer@2.0.1
```

The npm package can install and diagnose Hermes through its managed runtime:

```bash
hm-arch-install install hermes
hm-arch-install status hermes
hm-arch-install doctor hermes
```

## Hermes home

Hermes reads configuration from:

- `$HERMES_HOME/config.yaml` when `HERMES_HOME` is set, or
- `~/.hermes/config.yaml` by default

```bash
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
mkdir -p "$HERMES_HOME"
```

## Configure HM-Arch

Recommended:

```bash
hm-arch install hermes
# or:
hm-arch-install install hermes
```

Then restart Hermes so the running agent process loads the provider plugin.

Manual equivalent:

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

## Smoke test

```bash
hm-arch status hermes
hm-arch doctor hermes
```

With npm:

```bash
hm-arch-install status hermes
hm-arch-install doctor hermes
```

Expected when fully configured:

- `status` reports `installed` with role `memory-provider`
- `doctor` exits 0

Inspect all agents at once:

```bash
hm-arch status
hm-arch doctor
```

## Uninstall / disable

Recommended:

```bash
hm-arch uninstall hermes
# or:
hm-arch-install uninstall hermes
```

Manual equivalent:

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
- [npm installer](../npm-installer.md)
- [Integration CLI smoke tests](../integration-cli-smoke.md)
- [PyPI clean-install verification](../pypi-clean-install.md)
