# Release checklist

Use this checklist for each HM-Arch release.

**Distribution today:** coordinated GitHub Releases (wheel, sdist, standalone
binaries, release notes) for **v2.0.0** and later.

**Registries:** PyPI (`hm-arch`) and npm (`@hm-arch/installer`) use the same
semver from v2.0.0 onward. Publication is automated by tag-triggered workflows
when a maintainer pushes a `vX.Y.Z` tag:

- `.github/workflows/github-release.yml` creates the GitHub Release and assets.
- `.github/workflows/publish-pypi.yml` publishes `hm-arch` to PyPI.
- `.github/workflows/publish-npm.yml` publishes `@hm-arch/installer` to npm.

**Approval rule:** creating and pushing the release tag is the maintainer approval
gate. Automated Cursor/Codex agents must not create or push a release tag unless
explicitly instructed for a specific version.

**Required repository secrets / environments:**

- `PYPI_API_TOKEN` for the `pypi` environment
- `NPM_TOKEN` for the `npm` environment

Prepared release notes for v2.0.0: [RELEASE_NOTES_v2.0.0.md](RELEASE_NOTES_v2.0.0.md).

**Python requirement:** use **Python 3.10+** for build, install, and smoke tests. System
`python3` may be older (e.g. 3.9) and will fail `requires-python` checks — prefer
`python3.12`, `uv run`, or an explicit `python3.10`/`python3.11` binary.

Version alignment across channels: [VERSIONING.md](VERSIONING.md).

## 1. Test (required before any release artifact)

Run from a clean clone or fresh virtual environment:

```bash
uv sync
uv run pytest && uv run python examples/release_smoke.py
python scripts/validate_release_gate.py
```

Or with pip on Python 3.10+:

```bash
python3.12 -m pip install -e ".[dev]"
pytest
python examples/basic_usage.py
python examples/release_smoke.py
```

Optional but recommended:

```bash
python examples/agent_integration.py
uv run pytest tests/prd_benchmarks -m benchmark -v   # PRD scale (see docs/benchmarks.md)
uv run python scripts/run_prd_benchmarks.py
```

Confirm:

- [ ] All pytest tests pass offline (no API keys).
- [ ] `examples/basic_usage.py` completes without error.
- [ ] `examples/release_smoke.py` prints version and exercises the public API.
- [ ] `docs/api.md` is up to date (`uv run python scripts/generate_api_docs.py` produces no diff, or you commit the regeneration).

## 2. Build (local wheel/sdist)

Verify the package builds locally. Use **Python >= 3.10** (matches `requires-python` in `pyproject.toml`):

```bash
python3 --version   # must be >= 3.10
uv run --with build python -m build --outdir dist
```

Or without uv:

```bash
python3 --version
python3 -m pip install -U pip build
python3 -m build --outdir dist
```

Inspect artifacts under `dist/` (do not commit `dist/` — it is gitignored):

- [ ] Wheel and sdist names include the intended version from `src/hm_arch/_version.py` (e.g. `hm_arch-2.0.0-py3-none-any.whl`).
- [ ] Clean **wheel** install succeeds (isolated venv, Python 3.10+):

```bash
rm -rf /tmp/hm-arch-wheel-verify
python3.12 -m venv /tmp/hm-arch-wheel-verify
/tmp/hm-arch-wheel-verify/bin/pip install --upgrade pip
/tmp/hm-arch-wheel-verify/bin/pip install dist/hm_arch-*.whl
/tmp/hm-arch-wheel-verify/bin/python -c "import hm_arch; assert hm_arch.__version__ == '2.0.0'"
```

- [ ] Clean **sdist** install succeeds (separate isolated venv, Python 3.10+):

```bash
rm -rf /tmp/hm-arch-sdist-verify
python3.12 -m venv /tmp/hm-arch-sdist-verify
/tmp/hm-arch-sdist-verify/bin/pip install --upgrade pip build
/tmp/hm-arch-sdist-verify/bin/pip install dist/hm_arch-*.tar.gz
/tmp/hm-arch-sdist-verify/bin/python -c "import hm_arch; assert hm_arch.__version__ == '2.0.0'"
```

- [ ] Release smoke test passes from the **wheel** install (run from a directory outside the repo clone, using the installed package):

```bash
cd /tmp && /tmp/hm-arch-wheel-verify/bin/python /path/to/hm-arch/examples/release_smoke.py
```

Agents may run **Build** and install verification locally. Do **not** upload to
PyPI, TestPyPI, or npm unless a maintainer has approved registry publication for
this version.

## 3. Version and changelog (maintainer)

Follow [VERSIONING.md](VERSIONING.md):

- [ ] `src/hm_arch/_version.py` matches the release number.
- [ ] `CHANGELOG.md` has a dated section for this version (not only `[Unreleased]`).
- [ ] `docs/RELEASE_NOTES_vX.Y.Z.md` is prepared for GitHub Release copy-paste (absolute URLs only).
- [ ] `uv run python scripts/generate_api_docs.py` run and `docs/api.md` committed if changed.
- [ ] Release notes state which channels apply (GitHub only, or GitHub + PyPI, or GitHub + PyPI + npm).

## 4. Tag (explicit approval required; triggers publication)

Only after **Test** and **Build** succeed and a maintainer approves the version.
Pushing this tag triggers the three release workflows listed above. The GitHub
Release workflow builds artifacts and creates the release; the PyPI and npm
workflows wait for the matching GitHub Release before publishing.

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

- [ ] Tag name matches `__version__` (with `v` prefix).
- [ ] `docs/RELEASE_NOTES_vX.Y.Z.md` exists or the workflow will fall back to `CHANGELOG.md`.
- [ ] Repository secrets/environments for PyPI and npm are configured.

Automated Cursor/Codex agents: **do not create tags** unless explicitly instructed.

## 5. Publish GitHub Release (automatic on tag)

After the tag is pushed, the release workflow creates a GitHub Release for the
same version:

- [ ] Release title and tag match `vX.Y.Z`.
- [ ] Release notes describe supported layers, optional backends, offline defaults, benchmark evidence, and known limitations.
- [ ] Verified wheel and sdist artifacts from `dist/` are attached.
- [ ] If registries are also published for this version, notes document install commands and version pairing (see sections 6–7).

Automated Cursor/Codex agents: **do not create or edit GitHub Releases manually**
unless explicitly instructed; prefer the tag-triggered workflow.

## 6. Publish to PyPI (automatic on tag; v2.0.0+)

**v1.0.0** was GitHub-only; do not retroactively publish older versions without a
maintainer decision. From **v2.0.0** onward, PyPI publication may be part of the
approved release window.

Full reproducible **pip** and **pipx** verification (local wheel before upload,
PyPI after upload): [pypi-clean-install.md](pypi-clean-install.md).

Agent setup guides (must match shipped CLI): [agents/README.md](agents/README.md).

`.github/workflows/publish-pypi.yml` publishes after GitHub Release **5**
completes:

- [ ] Maintainer approved PyPI upload for version `X.Y.Z`.
- [ ] Upload uses artifacts built from the tagged commit; `hm_arch.__version__` matches `X.Y.Z`.
- [ ] Clean **pip** install from local wheel documented in [pypi-clean-install.md](pypi-clean-install.md) §1 passes (Python 3.10+).
- [ ] Clean **pipx** install from local wheel documented in [pypi-clean-install.md](pypi-clean-install.md) §2 passes.
- [ ] After upload: `pip install hm-arch==X.Y.Z` in a fresh venv passes (§1 post-publish).
- [ ] After upload: `pipx install hm-arch==X.Y.Z` smoke test passes (§2 post-publish).
- [ ] `hm-arch install codex` / `claude-code` smoke from pip-installed CLI passes ([integration-cli-smoke.md](integration-cli-smoke.md)).
- [ ] `hm-arch install hermes` / `uninstall hermes` / `status hermes` / `doctor hermes` documented and smoke-tested.
- [ ] `docs/RELEASE_NOTES_vX.Y.Z.md` prepared (e.g. [RELEASE_NOTES_v2.0.0.md](RELEASE_NOTES_v2.0.0.md) for the coordinated v2 release).
- [ ] GitHub Release notes mention `pip install hm-arch` when PyPI is live for this version.

Manual `twine upload` is only for recovery when the workflow is unavailable.

## 7. Publish to npm (automatic on tag; v2.0.0+)

From **v2.0.0** onward, `@hm-arch/installer` may be published in the same approved
release window as the matching Python package and GitHub Release.

`.github/workflows/publish-npm.yml` publishes after GitHub Release **5**
completes. Follow the full checklist in
[npm-installer-publication.md](npm-installer-publication.md) before pushing the
tag.

Summary gates:

- [ ] Maintainer approved npm publish for `@hm-arch/installer@X.Y.Z` (or documented pairing version).
- [ ] Package metadata documents which `hm-arch` Python version it installs.
- [ ] `cd packages/installer && npm test` passes locally; cross-platform CI (`.github/workflows/npm-installer-ci.yml`) is green.
- [ ] `npm pack` / dry-run install smoke test passes on supported platforms (macOS, Linux, Windows).
- [ ] `postinstall` does not modify agent configuration (installer uses explicit install commands).
- [ ] [npm-installer.md](npm-installer.md) matches shipped commands; GitHub Release notes document npm install and Python version pairing.

Manual `npm publish` is only for recovery when the workflow is unavailable.

## Quick reference

| Step | Command / artifact | Agent allowed? |
|------|-------------------|----------------|
| Test | `uv run pytest`, `examples/release_smoke.py`, `scripts/validate_release_gate.py` | Yes |
| npm installer test | `cd packages/installer && npm ci && npm test` | Yes |
| Build | `uv run --with build python -m build --outdir dist` (Python >= 3.10) | Yes (local only) |
| Verify install | wheel + sdist in throwaway venvs; pip/pipx per [pypi-clean-install.md](pypi-clean-install.md) | Yes |
| Docs | `uv run python scripts/generate_api_docs.py` | Yes |
| Tag | `git tag`, `git push origin vX.Y.Z` | No (unless asked); triggers release workflow |
| GitHub Release | `.github/workflows/github-release.yml` | Automatic after tag |
| PyPI | `.github/workflows/publish-pypi.yml` | Automatic after tag |
| npm | `.github/workflows/publish-npm.yml` | Automatic after tag |
