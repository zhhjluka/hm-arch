# npm installer publication checklist

Use this checklist when preparing `@hm-arch/installer` for registry publication
(planned v1.2.0+). Automated Cursor/Codex agents must **not** run `npm publish`
unless a maintainer explicitly instructs them for a specific version.

Cross-reference: [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) section 7,
[VERSIONING.md](VERSIONING.md), [npm-installer.md](npm-installer.md).

## Pre-publish verification

### Version alignment

- [ ] `src/hm_arch/_version.py` bumped to the target release `X.Y.Z`
- [ ] `packages/installer/package.json` version matches (or documented pairing version is recorded)
- [ ] `npm run build` in `packages/installer` refreshed `dist/bundled-version.json` to `X.Y.Z`
- [ ] Release notes state which `hm-arch` Python version the npm package installs by default

### Python artifact availability

- [ ] Matching `hm-arch==X.Y.Z` is on PyPI **or** a GitHub Release wheel URL is documented for pip
- [ ] `HM_ARCH_PIP_SPEC` override behavior documented if publishing before PyPI (emergency only)

### Local and CI smoke tests

- [ ] `cd packages/installer && npm ci && npm test` passes locally
- [ ] `python scripts/verify_release_versions.py` passes after `npm run build`
- [ ] Cross-platform CI ([`.github/workflows/npm-installer-ci.yml`](../.github/workflows/npm-installer-ci.yml)) is green on macOS, Linux, and Windows
- [ ] Clean-machine CI job (`clean-machine-standalone`) passes: npm tests run without Python on PATH when `HM_ARCH_STANDALONE_FIXTURE` is set
- [ ] `npm pack` produces a tarball; install in a throwaway directory succeeds
- [ ] `hm-arch-install --help` works from the packed install
- [ ] `hm-arch-install doctor` passes with Python 3.10+ on each target OS
- [ ] `postinstall` remains a no-op (no agent config changes on `npm install`)

### Documentation

- [ ] [npm-installer.md](npm-installer.md) matches shipped commands and environment variables
- [ ] GitHub Release notes include npm install examples (`npx`, global install)
- [ ] Python version pairing and `HM_ARCH_PYTHON` guidance included in release notes

## Maintainer approval (required before publish)

- [ ] Maintainer approved npm publish for `@hm-arch/installer@X.Y.Z`
- [ ] Registry credentials are configured only on maintainer-controlled systems (not committed to the repo)
- [ ] Two-factor authentication and npm org access verified for `@hm-arch` scope

## Publish commands (maintainers only)

```bash
cd packages/installer
npm ci
npm test
npm pack   # inspect tarball; optional dry-run install
npm publish --access public   # ONLY after explicit approval
```

Do **not** add `npm publish` to CI workflows.

## Post-publish verification

- [ ] `npm view @hm-arch/installer version` shows `X.Y.Z`
- [ ] Clean machine (Node only, supported standalone target): `npx @hm-arch/installer@X.Y.Z doctor` succeeds without system Python
- [ ] Clean machine: `npx @hm-arch/installer@X.Y.Z --help` succeeds
- [ ] Clean machine with Python 3.10+ (unsupported standalone targets): `npx @hm-arch/installer@X.Y.Z doctor` succeeds via managed venv
- [ ] Release notes and [CHANGELOG.md](../CHANGELOG.md) updated

## Quick reference

| Step | Command / artifact | Automated agent allowed? |
|------|-------------------|--------------------------|
| Build | `cd packages/installer && npm run build` | Yes |
| Test | `cd packages/installer && npm test` | Yes |
| Pack smoke | `npm pack` + install tarball locally | Yes |
| CI | `.github/workflows/npm-installer-ci.yml` | Yes (verify only) |
| Publish | `npm publish` | **No** (unless explicitly instructed) |
