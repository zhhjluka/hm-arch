# Release checklist

Use this checklist for each HM-Arch release.

**Distribution today:** GitHub Releases (wheel + sdist) for **v1.0.0** and until
PyPI/npm milestones in [agent-integration-roadmap.md](agent-integration-roadmap.md).

**Planned registries:** PyPI (`hm-arch`, v1.1.0+) and npm (`@hm-arch/installer`,
v1.2.0+). Registry publication is allowed when a maintainer explicitly approves
it for a given version — it is not forbidden by project policy, but it is never
automated without approval.

**Approval rule:** Git tags, GitHub Releases, PyPI uploads, and npm publishes all
require **explicit maintainer approval**. Automated Cursor/Codex agents must not
perform those steps unless explicitly instructed for a specific version.

Prepared release notes for v1.0.0: [RELEASE_NOTES_v1.0.0.md](RELEASE_NOTES_v1.0.0.md).

**Python requirement:** use **Python 3.10+** for build, install, and smoke tests. System
`python3` may be older (e.g. 3.9) and will fail `requires-python` checks — prefer
`python3.12`, `uv run`, or an explicit `python3.10`/`python3.11` binary.

Version alignment across channels: [VERSIONING.md](VERSIONING.md).

## 1. Test (required before any release artifact)

Run from a clean clone or fresh virtual environment:

```bash
uv sync
uv run pytest && uv run python examples/release_smoke.py
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

- [ ] Wheel and sdist names include the intended version from `src/hm_arch/_version.py` (e.g. `hm_arch-1.0.0-py3-none-any.whl`).
- [ ] Clean **wheel** install succeeds (isolated venv, Python 3.10+):

```bash
rm -rf /tmp/hm-arch-wheel-verify
python3.12 -m venv /tmp/hm-arch-wheel-verify
/tmp/hm-arch-wheel-verify/bin/pip install --upgrade pip
/tmp/hm-arch-wheel-verify/bin/pip install dist/hm_arch-*.whl
/tmp/hm-arch-wheel-verify/bin/python -c "import hm_arch; assert hm_arch.__version__ == '1.0.0'"
```

- [ ] Clean **sdist** install succeeds (separate isolated venv, Python 3.10+):

```bash
rm -rf /tmp/hm-arch-sdist-verify
python3.12 -m venv /tmp/hm-arch-sdist-verify
/tmp/hm-arch-sdist-verify/bin/pip install --upgrade pip build
/tmp/hm-arch-sdist-verify/bin/pip install dist/hm_arch-*.tar.gz
/tmp/hm-arch-sdist-verify/bin/python -c "import hm_arch; assert hm_arch.__version__ == '1.0.0'"
```

- [ ] Release smoke test passes from the **wheel** install (run from a directory outside the repo clone, using the installed package):

```bash
cd /tmp && /tmp/hm-arch-wheel-verify/bin/python /path/to/memashuman/examples/release_smoke.py
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

## 4. Tag (explicit approval required)

Only after **Test** and **Build** succeed and a maintainer approves the version:

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

- [ ] Tag name matches `__version__` (with `v` prefix).
- [ ] GitHub Release notes copied from `docs/RELEASE_NOTES_vX.Y.Z.md` and/or `CHANGELOG.md`.

Automated Cursor/Codex agents: **do not create tags** unless explicitly instructed.

## 5. Publish GitHub Release (explicit approval required)

After the tag is pushed, create a GitHub Release for the same version:

- [ ] Release title and tag match `vX.Y.Z`.
- [ ] Release notes describe supported layers, optional backends, offline defaults, benchmark evidence, and known limitations.
- [ ] Verified wheel and sdist artifacts from `dist/` are attached.
- [ ] If registries are also published for this version, notes document install commands and version pairing (see sections 6–7).

Automated Cursor/Codex agents: **do not create or edit GitHub Releases** unless explicitly instructed.

## 6. Publish to PyPI (explicit approval required; v1.1.0+)

Skip this section until the project begins PyPI publication per the integration
roadmap. **v1.0.0** was GitHub-only; do not retroactively publish older versions
without a maintainer decision.

Full reproducible **pip** and **pipx** verification (local wheel before upload,
PyPI after upload): [pypi-clean-install.md](pypi-clean-install.md).

Agent setup guides (must match shipped CLI): [agents/README.md](agents/README.md).

Only after GitHub Release **5** is complete (or in the same approved release window):

- [ ] Maintainer approved PyPI upload for version `X.Y.Z`.
- [ ] Upload uses artifacts built from the tagged commit; `hm_arch.__version__` matches `X.Y.Z`.
- [ ] Clean **pip** install from local wheel documented in [pypi-clean-install.md](pypi-clean-install.md) §1 passes (Python 3.10+).
- [ ] Clean **pipx** install from local wheel documented in [pypi-clean-install.md](pypi-clean-install.md) §2 passes.
- [ ] After upload: `pip install hm-arch==X.Y.Z` in a fresh venv passes (§1 post-publish).
- [ ] After upload: `pipx install hm-arch==X.Y.Z` smoke test passes (§2 post-publish).
- [ ] `hm-arch install codex` / `claude-code` smoke from pip-installed CLI passes ([integration-cli-smoke.md](integration-cli-smoke.md)).
- [ ] `hm-arch status hermes` / `doctor hermes` documented; install/uninstall hermes remain unsupported by design.
- [ ] `docs/RELEASE_NOTES_vX.Y.Z.md` prepared (e.g. [RELEASE_NOTES_v1.1.0.md](RELEASE_NOTES_v1.1.0.md) for Python-first integration).
- [ ] GitHub Release notes mention `pip install hm-arch` when PyPI is live for this version.

Example maintainer commands (requires credentials; agents must not run without approval):

```bash
python3 -m pip install -U twine
python3 -m twine upload dist/hm_arch-X.Y.Z*
```

Automated Cursor/Codex agents: **do not upload to PyPI or TestPyPI** unless explicitly instructed.

## 7. Publish to npm (explicit approval required; v1.2.0+)

Skip until `@hm-arch/installer` exists and the integration roadmap targets npm
for this release.

Only after the matching `hm-arch` Python version is available (PyPI or documented
GitHub wheel URL) and a maintainer approves npm publication:

- [ ] Maintainer approved npm publish for `@hm-arch/installer@X.Y.Z` (or documented pairing version).
- [ ] Package metadata documents which `hm-arch` Python version it installs.
- [ ] `npm pack` / dry-run install smoke test passes on supported platforms.
- [ ] `postinstall` does not modify agent configuration (installer uses explicit install commands).
- [ ] GitHub Release notes document npm install commands and Python version pairing.

Automated Cursor/Codex agents: **do not publish to npm** unless explicitly instructed.

## Quick reference

| Step | Command / artifact | Agent allowed? |
|------|-------------------|----------------|
| Test | `uv run pytest`, `examples/release_smoke.py` | Yes |
| Build | `uv run --with build python -m build --outdir dist` (Python >= 3.10) | Yes (local only) |
| Verify install | wheel + sdist in throwaway venvs; pip/pipx per [pypi-clean-install.md](pypi-clean-install.md) | Yes |
| Docs | `uv run python scripts/generate_api_docs.py` | Yes |
| Tag | `git tag`, `git push origin vX.Y.Z` | No (unless asked) |
| GitHub Release | Release notes + `dist/` artifacts | No (unless asked) |
| PyPI | `twine upload` / registry upload | No (unless asked) |
| npm | `npm publish` for `@hm-arch/installer` | No (unless asked) |
