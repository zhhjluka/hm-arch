# HM-Arch integration CLI smoke tests

Manual checks for `hm-arch install`, `uninstall`, `status`, and `doctor`.
Per-agent setup guides: [agents/README.md](agents/README.md).

## Install `hm-arch` for testing

**Editable (repository clone):**

```bash
cd /path/to/hm-arch
python3 -m pip install -e ".[dev]"
```

**Clean pip install (release wheel):** see [pypi-clean-install.md](pypi-clean-install.md).

**Clean pipx install:** see [pypi-clean-install.md](pypi-clean-install.md) §2.

All commands below are offline and do not require LLM/API keys.

OpenClaw end-to-end verification (automated + manual gateway smoke):
[openclaw-e2e-smoke.md](openclaw-e2e-smoke.md).

## Codex (project scope)

```bash
cd /tmp/hm-arch-smoke-codex
rm -rf .codex
hm-arch install codex
hm-arch status codex
hm-arch doctor codex
hm-arch uninstall codex
hm-arch status codex
```

Expected:

- `install` creates `.codex/hooks.json` with three HM-Arch hooks (recall, record, consolidate).
- `status` reports `installed` and lists hook roles.
- `doctor` exits 0 when hooks and Codex feature flags are present.
- `uninstall` removes only HM-Arch-owned hooks; pre-existing user hooks are preserved.

## Claude Code (project scope)

```bash
cd /tmp/hm-arch-smoke-claude
rm -rf .claude
hm-arch install claude-code
hm-arch status claude-code
hm-arch doctor claude-code
hm-arch uninstall claude-code
```

Expected: same lifecycle as Codex, using `.claude/settings.json`.

## Hermes (native plugin bridge)

```bash
export HERMES_HOME=/tmp/hm-arch-smoke-hermes
mkdir -p "$HERMES_HOME"
hm-arch install hermes
hm-arch status hermes
hm-arch doctor hermes
hm-arch uninstall hermes
```

With `memory.provider: mem0` in `$HERMES_HOME/config.yaml`, `status` and `doctor`
should report a provider conflict with remediation text.

Expected: install writes the HM-Arch provider config and plugin bridge,
doctor initializes the SQLite schema, and uninstall removes HM-Arch-owned
config/bridge files while preserving the memory database.

## OpenClaw (memory plugin + sidecar)

```bash
export OPENCLAW_STATE_DIR=/tmp/hm-arch-smoke-openclaw
mkdir -p /tmp/hm-arch-smoke-project
cd /tmp/hm-arch-smoke-project

hm-arch install openclaw
hm-arch status openclaw
hm-arch doctor openclaw
hm-arch uninstall openclaw
```

Expected:

- `install` exits `0` and prints `openclaw (project): installed`
- `status` reports `plugins.slots.memory is set to 'memory-hm-arch'`
- `doctor` exits `0` with database schema initialized
- plugin manifest exists under
  `/tmp/hm-arch-smoke-project/.openclaw/extensions/memory-hm-arch/`
- `uninstall` removes HM-Arch config and plugin files; database is preserved

`OPENCLAW_STATE_DIR` controls global-scope installs. This example intentionally
uses project scope, so its config and extension files live under the current
project's `.openclaw/` directory.

With another provider occupying `plugins.slots.memory`, `status` and `doctor`
should report a memory-slot conflict with remediation text.

Gateway-level end-to-end verification:
[openclaw-e2e-smoke.md](openclaw-e2e-smoke.md). Setup guide:
[agents/openclaw.md](agents/openclaw.md).

## Automated offline tests

```bash
pytest tests/test_integrations_cli_manage.py tests/test_codex_installer.py tests/test_claude_code_installer.py -q
```
