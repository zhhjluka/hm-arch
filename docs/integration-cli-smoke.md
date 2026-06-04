# HM-Arch integration CLI smoke tests

Manual checks for `hm-arch install`, `uninstall`, `status`, and `doctor`.
Per-agent setup guides: [agents/README.md](agents/README.md).

## Install `hm-arch` for testing

**Editable (repository clone):**

```bash
cd /path/to/memashuman
python3 -m pip install -e ".[dev]"
```

**Clean pip install (release wheel):** see [pypi-clean-install.md](pypi-clean-install.md).

**Clean pipx install:** see [pypi-clean-install.md](pypi-clean-install.md) §2.

All commands below are offline and do not require LLM/API keys.

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

## Hermes (config inspection)

```bash
export HERMES_HOME=/tmp/hm-arch-smoke-hermes
mkdir -p "$HERMES_HOME"
hm-arch status hermes
hm-arch doctor hermes
```

With `memory.provider: mem0` in `$HERMES_HOME/config.yaml`, `status` and `doctor`
should report a provider conflict with remediation text.

`hm-arch install hermes` and `hm-arch uninstall hermes` are intentionally
unsupported; Hermes registers HM-Arch through its plugin system.

## Automated offline tests

```bash
pytest tests/test_integrations_cli_manage.py tests/test_codex_installer.py tests/test_claude_code_installer.py -q
```
