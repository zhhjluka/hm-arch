# v2.0.0 migration and compatibility guide

This document prepares users and maintainers for **v2.0.0: Python-free npm
installation** ([agent-integration-roadmap.md](agent-integration-roadmap.md)).

v2.0.0 adds a verified standalone executable path for `@hm-arch/installer` so
Node.js users on supported platforms can manage Codex, Claude Code, and Hermes
integrations **without a system Python runtime**. Existing Python and pip
workflows remain fully supported.

## Who needs to migrate?

| User profile | Action required |
|--------------|-----------------|
| `pip` / `pipx` / editable installs of `hm-arch` | **None** — continue using `hm-arch` directly |
| npm users on supported standalone targets (linux x86_64/aarch64, darwin arm64, windows x86_64) | **Optional** — set `HM_ARCH_RUNTIME=standalone` or use default `auto` once release artifacts are published |
| npm users on unsupported targets (Intel Mac, Windows ARM64) | Keep `HM_ARCH_RUNTIME=python` or use pip/pipx |
| Maintainers publishing releases | Coordinate versions across GitHub, PyPI, and npm (see below) |

No automatic migration from Python to npm is performed. The npm installer is an
installer and launcher; memory data stays in SQLite under the configured
`HM_ARCH_DB_PATH` / project layout.

## Version coordination (v2.0.0+)

All public channels share one semver per release:

| Channel | Package / artifact | Version source |
|---------|-------------------|----------------|
| Python (SSoT) | `hm-arch` | `src/hm_arch/_version.py` |
| GitHub Releases | wheel, sdist, standalone binaries | tag `vX.Y.Z` |
| PyPI | `hm-arch` | same `X.Y.Z` |
| npm | `@hm-arch/installer` | `packages/installer/package.json` |

Before tagging a release, run:

```bash
(cd packages/installer && npm run build)
python scripts/verify_release_versions.py
```

CI and the npm test suite include version-coordination checks. Intentional
version skew between channels must be documented in release notes.

## Standalone vs Python runtime

| `HM_ARCH_RUNTIME` | Behavior |
|-------------------|----------|
| `auto` (default) | Use standalone on supported targets; fall back to managed Python venv when standalone is unavailable or download fails |
| `standalone` | Require verified standalone binary; fail if unavailable |
| `python` | Always use managed Python venv (previous v1.2.x behavior) |

Environment variables unchanged: `HM_ARCH_HOME`, `HM_ARCH_RELEASE_BASE_URL`,
`HM_ARCH_PIP_SPEC`, `HM_ARCH_PYTHON`.

## Agent integration compatibility

| Agent | Standalone `hm-arch` | npm `hm-arch-install` | Notes |
|-------|---------------------|------------------------|-------|
| Codex | install / status / doctor / uninstall | same via delegation | Hooks under `.codex/hooks.json` |
| Claude Code | install / status / doctor / uninstall | same via delegation | Hooks under `.claude/settings.json` |
| Hermes | status / doctor only | same via delegation | Install/uninstall unsupported by design; configure Hermes provider manually |

See [agents/compatibility-matrix.md](agents/compatibility-matrix.md) for full
capability details.

## Database and configuration

- SQLite schema migrations are backward compatible within the same major line;
  run `hm-arch doctor` after upgrading.
- Agent hook files are not rewritten on `npm install`; use explicit
  `hm-arch-install install <agent>` (or `hm-arch install <agent>`).
- Shared-memory and project/global split policies are unchanged; see
  [memory-sharing-policies.md](memory-sharing-policies.md).

## Upgrade path from v1.x npm installer

1. Install Node.js 18+.
2. On a supported platform, ensure GitHub Release standalone artifacts exist for
   your target version (or set `HM_ARCH_RELEASE_BASE_URL` for a mirror).
3. Run `hm-arch-install upgrade` to refresh the standalone binary or Python venv.
4. Run `hm-arch-install doctor` for each agent you use.
5. Python-only users can ignore npm entirely.

## Rollback

- Set `HM_ARCH_RUNTIME=python` and run `hm-arch-install upgrade` to recreate the
  managed venv.
- Uninstall npm package: `npm uninstall -g @hm-arch/installer` — does not remove
  SQLite databases or agent hook files installed by `hm-arch`.

## Maintainer release checklist (v2.0.0)

1. Bump `src/hm_arch/_version.py` and `packages/installer/package.json` together.
2. Build standalone artifacts for all matrix targets (see
   [standalone-executable.md](standalone-executable.md)).
3. Attach artifacts and `standalone-release-metadata.json` to the GitHub Release.
4. Run full offline suite: `uv run pytest` and `cd packages/installer && npm test`.
5. Run clean-machine verification (CI job `clean-machine-standalone` or local
   equivalent with `HM_ARCH_STANDALONE_FIXTURE`).
6. Publish PyPI and npm only after explicit maintainer approval
   ([RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)).

## Related documentation

- [npm-installer.md](npm-installer.md) — installer commands and environment variables
- [VERSIONING.md](VERSIONING.md) — semver and channel policy
- [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) — publication gates
- [agent-integration-roadmap.md](agent-integration-roadmap.md) — v2.0.0 scope
