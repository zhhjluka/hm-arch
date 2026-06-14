# npm installer (`@hm-arch/installer`)

The `@hm-arch/installer` npm package is an installer and launcher for HM-Arch agent
integrations. It does **not** reimplement memory logic in TypeScript; it uses the
matching standalone `hm-arch` executable on supported targets, or falls back to a
managed Python virtual environment that installs the matching `hm-arch` package.

**Status:** published for the coordinated v2.0.3 line. Install with
`npm install -g @hm-arch/installer@2.0.3` or use `npx @hm-arch/installer@2.0.3`.
Automated agents must **not** run `npm publish` without maintainer approval.

See also:

- [agent-integration-roadmap.md](agent-integration-roadmap.md) — v2.0.0 Python-free npm path
- [v2-migration-guide.md](v2-migration-guide.md) — v2.0.0 migration and compatibility
- [npm-installer-publication.md](npm-installer-publication.md) — maintainer publication checklist
- [VERSIONING.md](VERSIONING.md) — cross-channel semver alignment
- [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) — release and registry policy

## Requirements

| Component | Minimum | Notes |
|-----------|---------|-------|
| Node.js | **18.x+** | Declared in `packages/installer/package.json` `engines.node` |
| Python | **3.10+** (optional on supported standalone targets) | Required when `HM_ARCH_RUNTIME=python` or standalone artifacts are unavailable |
| OS | **macOS, Linux, Windows** | `darwin`, `linux`, `win32`; other platforms are unsupported |

### Standalone binary targets (MEM-62 / MEM-63)

When `HM_ARCH_RUNTIME` is `auto` (default) or `standalone`, the installer downloads a
verified PyInstaller executable from GitHub Releases:

| OS | Architectures |
|----|----------------|
| linux | `x86_64`, `aarch64` |
| darwin | `arm64` only (not Intel/x64) |
| windows | `x86_64` only (not ARM64) |

Artifacts are named `hm-arch-{version}-{os}-{arch}[.exe]` and verified against
`hm-arch-{version}-standalone-release-metadata.json` and per-file `.sha256` checksums
before installation under `<HM_ARCH_HOME>/standalone/`.

If the GitHub repository is private, unauthenticated npm installs cannot download
standalone release assets and GitHub returns 404. Set `HM_ARCH_RUNTIME=python`
to use the PyPI-backed managed Python runtime instead.

### Supported Python discovery

The installer probes interpreters in this order:

1. `HM_ARCH_PYTHON` — explicit path override (recommended when multiple Pythons are installed)
2. `python3.13`, `python3.12`, `python3.11`, `python3.10`, `python3`, `python`

Only interpreters at or above Python 3.10 are accepted for managed environment creation.

### Managed runtime behavior

On first use of commands that need the Python core (`install`, `upgrade`, and delegated
`status` / `doctor` / `uninstall`), the installer:

1. Creates an isolated virtual environment under the HM-Arch home directory
2. Installs `hm-arch` with the managed `pip` inside that venv (never global `pip install`)
3. Records state in `python-env/state.json` (installed version, Python path, timestamps)
4. Delegates agent subcommands to `hm-arch` inside the managed venv

Default home directories:

| Platform | Default `HM_ARCH_HOME` |
|----------|------------------------|
| macOS / Linux | `~/.hm-arch` |
| Windows | `%LOCALAPPDATA%\hm-arch` |

Managed venv path: `<HM_ARCH_HOME>/python-env/`

### Environment variables

| Variable | Purpose |
|----------|---------|
| `HM_ARCH_HOME` | Override the managed-runtime root directory |
| `HM_ARCH_PYTHON` | Path to a Python 3.10+ interpreter used to create the venv |
| `HM_ARCH_PIP_SPEC` | pip requirement for `hm-arch` (default: `hm-arch==<bundled>`) |
| `HM_ARCH_RUNTIME` | `auto` (default), `standalone`, or `python` |
| `HM_ARCH_RELEASE_BASE_URL` | Override GitHub release download base URL (tests/mirrors) |

The bundled Python package version is synced from `src/hm_arch/_version.py` at build
time into `dist/bundled-version.json`. At runtime the default pip spec is
`hm-arch==<bundled version>` unless `HM_ARCH_PIP_SPEC` is set (useful for editable
monorepo installs during development).

## npm and Python version compatibility

| Channel | Package | Version source | Pairing rule |
|---------|---------|----------------|--------------|
| GitHub Releases | wheel + sdist | `src/hm_arch/_version.py` | Primary artifact today |
| PyPI | `hm-arch` | same semver (v2.0.0+) | Must match GitHub release for `X.Y.Z` |
| npm | `@hm-arch/installer` | `packages/installer/package.json` (v2.0.0+) | Bundled default installs matching `hm-arch==X.Y.Z` |

Coordination rules:

- Bump `src/hm_arch/_version.py` once per release.
- Rebuild the npm package so `sync-bundled-version.mjs` refreshes `bundled-version.json`.
- Publish npm only after the matching `hm-arch` Python version is available on PyPI or
  documented via a GitHub Release wheel URL in release notes.
- Record any intentional version skew in release notes (avoid silent mismatches).

## Usage

### End-user commands

```bash
# One-shot install for a supported agent
npx @hm-arch/installer@2.0.3 install codex
npx @hm-arch/installer@2.0.3 install claude-code

# Hermes: install the memory provider bridge, update config.yaml, then restart Hermes.
npx @hm-arch/installer@2.0.3 install hermes
npx @hm-arch/installer@2.0.3 status hermes
npx @hm-arch/installer@2.0.3 doctor hermes

# Global CLI after npm install -g
npm install -g @hm-arch/installer@2.0.3
hm-arch-install doctor
hm-arch-install status codex
hm-arch-install install hermes
hm-arch-install status hermes
hm-arch-install upgrade
hm-arch-install uninstall codex
```

Supported agents: `codex`, `claude-code`, `hermes`.

Supported subcommands: `install`, `status`, `doctor`, `upgrade`, `uninstall`.
For Hermes, `install hermes` writes the HM-Arch provider config and plugin bridge
under `$HERMES_HOME` (default: `~/.hermes`). Restart Hermes after install so the
running agent process loads the plugin.

Flags: `--global` / `-g`, `--help` / `-h`.

### Local development (monorepo)

```bash
cd packages/installer
npm ci
npm test
```

Editable Python install for integration tests:

```bash
export HM_ARCH_HOME="$(mktemp -d)"
export HM_ARCH_PIP_SPEC="/path/to/hm-arch/repo/root"
export HM_ARCH_PYTHON="$(command -v python3)"
node dist/cli.js doctor
```

### postinstall is intentionally a no-op

`npm install` does **not** modify Codex, Claude Code, or Hermes configuration.
Run `hm-arch-install install <agent>` explicitly after environment checks pass.
For Hermes, run `hm-arch-install install hermes`, restart Hermes, then validate
with `hm-arch-install status hermes` and `hm-arch-install doctor hermes`.

## CI verification

GitHub Actions workflow [`.github/workflows/npm-installer-ci.yml`](../.github/workflows/npm-installer-ci.yml)
runs on **ubuntu-latest**, **macos-latest**, and **windows-latest**:

- `npm ci`
- `npm test` (TypeScript build, unit tests, Python integration tests when Python 3.10+ is present, pack smoke)
- Explicit packed-tarball install + `hm-arch-install --help` smoke (no registry publish)

A companion **ubuntu** job runs offline Python installer tests:

```bash
pytest tests/test_codex_installer.py tests/test_claude_code_installer.py tests/test_integrations_cli_manage.py -q
```

## Maintainer approval gates

These actions require explicit maintainer approval:

- `npm publish` for `@hm-arch/installer`
- Creating release tags or GitHub Releases that advertise npm install commands
- Any registry credential configuration in CI

CI in this repository verifies install/build/test behavior only. See
[npm-installer-publication.md](npm-installer-publication.md) for the full pre-publish checklist.
