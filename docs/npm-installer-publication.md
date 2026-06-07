# npm installer publication checklist

Use this checklist when preparing `@hm-arch/installer` for registry publication
(`v2.0.0+`). The normal path is the tag-triggered
`.github/workflows/publish-npm.yml` workflow, which waits for the matching
GitHub Release before publishing. Automated Cursor/Codex agents must **not**
create or push release tags unless a maintainer explicitly instructs them for a
specific version.

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

- [ ] Maintainer approved release tag `vX.Y.Z`
- [ ] `NPM_TOKEN` is configured for the `npm` environment
- [ ] Registry credentials are configured only on maintainer-controlled systems (not committed to the repo)
- [ ] Two-factor authentication and npm org access verified for `@hm-arch` scope

## Publish path

Push the release tag after all checks pass:

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

The release workflow runs `npm publish --access public` after creating the GitHub
Release. Manual `npm publish` is only for recovery when the workflow is
unavailable.

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
| Publish | tag-triggered release workflow | Automatic after approved tag |
