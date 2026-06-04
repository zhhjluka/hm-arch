# HM-Arch v1.1.0 — Python-first three-agent integration

**Draft release notes** for the Python-first integration MVP. Use this document for
GitHub Release copy-paste after maintainer approval. Adjust version strings and
install commands to match the published channels for that release.

**Publication:** PyPI upload requires **explicit maintainer approval**. Automated
agents must not publish to PyPI, TestPyPI, or npm without instruction.

## Install

### PyPI (after maintainer-approved publish)

```bash
python3 --version   # requires Python >= 3.10
pip install hm-arch==1.1.0
# or isolated CLI:
pipx install hm-arch==1.1.0
hm-arch --help
python -c "import hm_arch; print(hm_arch.__version__)"
```

### GitHub Release (always)

Download `hm_arch-1.1.0-py3-none-any.whl` and/or `hm_arch-1.1.0.tar.gz` from the
release assets:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install /path/to/hm_arch-1.1.0-py3-none-any.whl
```

Maintainer verification steps: [pypi-clean-install.md](pypi-clean-install.md).

## What's new

### Packaged `hm-arch` CLI

Console entry point with adapter runtime and agent management:

```text
hm-arch recall | record | consolidate   # JSON adapter protocol (stdin/stdout)
hm-arch codex recall | record | consolidate
hm-arch claude-code recall | record | consolidate
hm-arch install <agent> [--global]
hm-arch uninstall <agent> [--global]
hm-arch status [agent] [--global]
hm-arch doctor [agent] [--global]
```

### Codex and Claude Code installers

- **Codex:** `hm-arch install codex` writes `.codex/hooks.json` and enables hooks
  in `.codex/config.toml`. Hooks call `hm-arch codex …`.
- **Claude Code:** `hm-arch install claude-code` merges into `.claude/settings.json`.
  Hooks call `hm-arch claude-code …`.
- Idempotent install; uninstall removes only HM-Arch-owned hooks.

Setup guides:

- https://github.com/ZhangHangjianMA/memashuman/blob/v1.1.0/docs/agents/codex.md
- https://github.com/ZhangHangjianMA/memashuman/blob/v1.1.0/docs/agents/claude-code.md

### Hermes Agent Memory Provider

- Native Hermes Memory Provider in `hm_arch.integrations.hermes`
- Configure via `$HERMES_HOME/config.yaml` (`memory.provider: hm-arch`,
  `plugins.hm-arch`)
- **`hm-arch install hermes` / `uninstall hermes` are not supported** — use
  `hm-arch status hermes` and `hm-arch doctor hermes` for inspection
- Refuses to silently replace another configured external memory provider

Setup guide:
https://github.com/ZhangHangjianMA/memashuman/blob/v1.1.0/docs/agents/hermes.md

### Documentation

- Agent setup guides under `docs/agents/`
- PyPI/pipx clean-install verification: `docs/pypi-clean-install.md`
- Integration CLI smoke tests: `docs/integration-cli-smoke.md`

## Quick start (Codex)

```bash
pip install hm-arch   # after PyPI approval
cd your-project
hm-arch install codex
hm-arch doctor codex
```

## Uninstall

```bash
hm-arch uninstall codex
hm-arch uninstall claude-code
# Hermes: edit config.yaml manually — see docs/agents/hermes.md
pip uninstall hm-arch
# pipx: pipx uninstall hm-arch
```

## Unchanged from v1.0.0

- Offline-first `HMArch` facade (L0–L6), SQLite source of truth, optional ChromaDB
  and LLM backends with local fallback
- No npm `@hm-arch/installer` in this release (planned v1.2.0+)
- No MCP server

## Known limitations

- Hermes hook installation is manual (config + plugin registration); CLI
  management is status/doctor only
- Single-process, single-agent memory database per configuration
- PyPI and npm publication require maintainer approval per release

## Verification

```bash
pytest
python examples/release_smoke.py
pytest tests/test_integrations_cli_manage.py -q
```

See [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) for the full release workflow.
