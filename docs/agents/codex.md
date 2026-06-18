# Codex setup (HM-Arch)

Install HM-Arch, wire Codex lifecycle hooks, smoke-test, and uninstall. All steps
are offline and do not require API keys.

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
# or isolated CLI on PATH:
pipx install hm-arch
```

**From npm**:

```bash
npm install -g @hm-arch/installer
hm-arch-install install codex
```

Confirm the CLI:

```bash
hm-arch --help
# or, after npm install:
hm-arch-install --help
```

## Connect Codex (project scope)

Run from your project root (where you want `.codex/`):

```bash
cd /path/to/your/project
hm-arch install codex
```

This creates or updates:

- `.codex/hooks.json` — three HM-Arch hooks (`recall`, `record`, `consolidate`)
  invoking `hm-arch codex recall|record|consolidate`
- `.codex/config.toml` — enables `[features] hooks = true` when needed

### Global installation

```bash
hm-arch install codex --global
hm-arch status codex --global
hm-arch uninstall codex --global
```

## Smoke test

```bash
cd /path/to/your/project
hm-arch status codex
hm-arch doctor codex
```

Expected when installed:

- `status` reports `installed` and lists roles `recall`, `record`, `consolidate`
- `doctor` exits 0 when hooks and Codex hook feature flags are valid
- Hooks use `hm-arch codex …` when `hm-arch` is on `PATH`

### Verify the HM-Arch bridge

Use the bridge commands first. They do not require a Codex model call and make it
clear whether HM-Arch can record and recall memory:

```bash
cd /path/to/your/project
printf '%s' '{"prompt":"Codex-HM-Arch-local-check","last_assistant_message":"Stored through HM-Arch."}' \
  | hm-arch codex record

printf '%s' '{"hook_event_name":"UserPromptSubmit","prompt":"Codex-HM-Arch-local-check"}' \
  | hm-arch codex recall
```

The recall output should be JSON with:

- `hookSpecificOutput.hookEventName` set to `UserPromptSubmit`
- `hookSpecificOutput.additionalContext` containing an `HM-Arch recalled memory`
  section

Then open an interactive Codex CLI session from the same project:

```bash
codex --cd /path/to/your/project
```

Run `/hooks` and trust the HM-Arch hooks if Codex marks them as new or changed.
Codex only runs project-local hooks after the project `.codex/` layer is trusted;
changed command hooks also need review before they run.

For an isolated HM-Arch test, temporarily disable Codex native memories so their
local file-backed context does not hide whether HM-Arch is working:

```bash
codex --cd /path/to/your/project --disable memories
```

Do not use `codex exec` as the lifecycle hook smoke test. It is useful for
non-interactive prompts, but HM-Arch validation should use the direct bridge
commands above plus an interactive Codex session with `/hooks` review.

Optional lifecycle check in a throwaway directory:

```bash
mkdir -p /tmp/hm-arch-codex-smoke && cd /tmp/hm-arch-codex-smoke
rm -rf .codex
hm-arch install codex && hm-arch status codex && hm-arch doctor codex
hm-arch uninstall codex
```

## Uninstall

```bash
cd /path/to/your/project
hm-arch uninstall codex
```

Only HM-Arch-owned hooks are removed; your own hooks in `.codex/hooks.json` are
preserved.

## Database path

Hooks use the packaged adapter. Set `HM_ARCH_DB_PATH` to a SQLite file, or omit it
to use `./.hm_arch_agent_memory.db` in the Codex working directory.

## Manual / example hooks

Portable example scripts (not auto-installed) live under
`examples/codex_hooks/`. See [examples/codex_hooks/README.md](../../examples/codex_hooks/README.md).

## Related docs

- [Claude Code setup](claude-code.md)
- [Hermes setup](hermes.md)
- [OpenClaw setup](openclaw.md)
- [Integration CLI smoke tests](../integration-cli-smoke.md)
- [PyPI clean-install verification](../pypi-clean-install.md)
