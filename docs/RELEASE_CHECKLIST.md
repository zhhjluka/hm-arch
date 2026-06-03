# Release checklist

Use this checklist for each HM-Arch release. HM-Arch releases are distributed
through **GitHub Releases only**. **Git tags and GitHub Releases require explicit
human approval**. HM-Arch is **not** published to PyPI or any package registry.

Prepared release notes for v1.0.0: [RELEASE_NOTES_v1.0.0.md](RELEASE_NOTES_v1.0.0.md).

**Python requirement:** use **Python 3.10+** for build, install, and smoke tests. System
`python3` may be older (e.g. 3.9) and will fail `requires-python` checks — prefer
`python3.12`, `uv run`, or an explicit `python3.10`/`python3.11` binary.

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

## 2. Build (local wheel/sdist only)

Verify the package builds without publishing to any registry:

```bash
uv run --with build python -m build
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
/tmp/hm-arch-sdist-verify/bin/pip install --upgrade pip
/tmp/hm-arch-sdist-verify/bin/pip install dist/hm_arch-*.tar.gz
/tmp/hm-arch-sdist-verify/bin/python -c "import hm_arch; assert hm_arch.__version__ == '1.0.0'"
```

- [ ] Release smoke test passes from the **wheel** install (run from a directory outside the repo clone, using the installed package):

```bash
cd /tmp && /tmp/hm-arch-wheel-verify/bin/python /path/to/memashuman/examples/release_smoke.py
```

Do **not** upload artifacts to PyPI, TestPyPI, or any other package registry.

## 3. Version and changelog (maintainer)

Follow [VERSIONING.md](VERSIONING.md):

- [ ] `src/hm_arch/_version.py` matches the release number.
- [ ] `CHANGELOG.md` has a dated section for this version (not only `[Unreleased]`).
- [ ] `docs/RELEASE_NOTES_vX.Y.Z.md` is prepared for GitHub Release copy-paste (absolute URLs only).
- [ ] `uv run python scripts/generate_api_docs.py` run and `docs/api.md` committed if changed.

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
- [ ] No package registry upload is performed.

## Quick reference

| Step | Command / artifact | Agent allowed? |
|------|-------------------|----------------|
| Test | `uv run pytest`, `examples/release_smoke.py` | Yes |
| Build | `uv run --with build python -m build` | Yes (local only) |
| Verify install | wheel + sdist in throwaway venvs (Python 3.10+) | Yes |
| Docs | `uv run python scripts/generate_api_docs.py` | Yes |
| Tag | `git tag`, `git push origin vX.Y.Z` | No (unless asked) |
| GitHub Release | Release notes + `dist/` artifacts | No (unless asked) |
| PyPI / registry | — | **Never** |
