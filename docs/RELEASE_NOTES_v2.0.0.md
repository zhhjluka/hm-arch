# HM-Arch v2.0.0 — coordinated Python, npm, and standalone release

HM-Arch **2.0.0** is the first coordinated release line for the Python package,
the npm installer, and standalone executable artifacts.

**Publication requires explicit maintainer approval.** Automated agents may
prepare files, run tests, and build local artifacts, but must not create tags,
publish GitHub Releases, upload to PyPI, or run `npm publish` unless explicitly
instructed for `v2.0.0`.

## Install

### GitHub Release

Download `hm_arch-2.0.0-py3-none-any.whl` and/or `hm_arch-2.0.0.tar.gz` from the
release assets:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install /path/to/hm_arch-2.0.0-py3-none-any.whl
hm-arch --help
python -c "import hm_arch; print(hm_arch.__version__)"
```

### PyPI (after maintainer-approved publish)

```bash
pip install hm-arch==2.0.0
# or isolated CLI:
pipx install hm-arch==2.0.0
hm-arch --help
```

### npm (after maintainer-approved publish)

```bash
npm install -g @hm-arch/installer@2.0.0
hm-arch-install doctor
```

One-shot usage is also supported:

```bash
npx @hm-arch/installer@2.0.0 doctor
```

## What's new

### Python-free npm path

`@hm-arch/installer` can now use verified standalone executables on supported
targets, so Node.js users can run HM-Arch agent management commands without a
preinstalled Python runtime.

Supported standalone targets:

| OS | Architectures |
|----|---------------|
| linux | `x86_64`, `aarch64` |
| darwin | `arm64` |
| windows | `x86_64` |

Unsupported targets, such as Intel macOS and Windows ARM64, can continue using
the managed Python runtime with `HM_ARCH_RUNTIME=python`.

### Shared `hm-arch` CLI

The Python package exposes the same CLI surface used by direct Python users,
agent hooks, and the npm installer:

```text
hm-arch recall | record | consolidate
hm-arch codex recall | record | consolidate
hm-arch claude-code recall | record | consolidate
hm-arch install <agent> [--global]
hm-arch uninstall <agent> [--global]
hm-arch status [agent] [--global]
hm-arch doctor [agent] [--global]
```

### Agent integrations

- **Codex:** idempotent project/global hook installation via `hm-arch install codex`.
- **Claude Code:** idempotent `.claude/settings.json` merge via
  `hm-arch install claude-code`.
- **Hermes:** native Memory Provider foundation with `status` and `doctor`
  support; install/uninstall remain manual by design.

Setup guides:

- https://github.com/ZhangHangjianMA/hm-arch/blob/v2.0.0/docs/agents/codex.md
- https://github.com/ZhangHangjianMA/hm-arch/blob/v2.0.0/docs/agents/claude-code.md
- https://github.com/ZhangHangjianMA/hm-arch/blob/v2.0.0/docs/agents/hermes.md

### Version coordination

All release channels use `2.0.0`:

| Channel | Version |
|---------|---------|
| Python package `hm-arch` | `2.0.0` |
| GitHub Release tag | `v2.0.0` |
| npm package `@hm-arch/installer` | `2.0.0` |
| Standalone artifacts | `hm-arch-2.0.0-{os}-{arch}` |

The release includes automated version checks for Python, npm, bundled installer
metadata, and standalone release naming.

## Runtime selection

`HM_ARCH_RUNTIME` controls npm installer behavior:

| Value | Behavior |
|-------|----------|
| `auto` | Prefer standalone on supported targets; fall back to managed Python |
| `standalone` | Require a verified standalone binary |
| `python` | Always use the managed Python virtual environment |

See [v2-migration-guide.md](v2-migration-guide.md) and
[npm-installer.md](npm-installer.md) for details.

## Unchanged from v1.0.0

- Offline-first `HMArch` facade with SQLite source of truth
- L0-L6 memory layers, retention-aware retrieval, forgetting, and consolidation
- Optional OpenAI, DeepSeek, and ChromaDB backends with local fallback defaults
- No automatic agent configuration changes during package installation

## Known limitations

- Standalone binaries are not built for every OS/architecture combination.
- Hermes hook installation is manual; CLI management is status/doctor only.
- Registry publication requires maintainer action and credentials.
- The npm package is an installer/launcher; memory logic remains in HM-Arch.

## Verification

Before tagging or publishing:

```bash
uv run pytest
(cd packages/installer && npm test)
python scripts/verify_release_versions.py
uv run python examples/release_smoke.py
```

Full release gates:

- https://github.com/ZhangHangjianMA/hm-arch/blob/v2.0.0/docs/RELEASE_CHECKLIST.md
- https://github.com/ZhangHangjianMA/hm-arch/blob/v2.0.0/docs/pypi-clean-install.md
- https://github.com/ZhangHangjianMA/hm-arch/blob/v2.0.0/docs/npm-installer-publication.md
