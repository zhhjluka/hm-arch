# Release checklist

Use this checklist for each HM-Arch release. **PyPI publish and git tags require explicit human approval** — automated agents must stop after the **Test** and **Build** sections unless a maintainer requests otherwise.

## 1. Test (required before any release artifact)

Run from a clean clone or fresh virtual environment:

```bash
python -m pip install -e ".[dev]"
pytest
python examples/basic_usage.py
python examples/release_smoke.py
```

Optional but recommended:

```bash
python examples/agent_integration.py
uv sync && uv run pytest
```

Confirm:

- [ ] All pytest tests pass offline (no API keys).
- [ ] `examples/basic_usage.py` completes without error.
- [ ] `examples/release_smoke.py` prints version and exercises the public API.
- [ ] `docs/api.md` is up to date (`python scripts/generate_api_docs.py` produces no diff, or you commit the regeneration).

## 2. Build (local wheel/sdist only)

Verify the package builds without publishing:

```bash
python -m pip install build
python -m build
```

Inspect artifacts under `dist/`:

- [ ] Wheel and sdist names include the intended version from `src/hm_arch/_version.py`.
- [ ] `pip install dist/hm_arch-*.whl` works in a throwaway venv.

Do **not** upload to PyPI in this step.

## 3. Version and changelog (maintainer)

Follow [VERSIONING.md](VERSIONING.md):

- [ ] `src/hm_arch/_version.py` matches the release number.
- [ ] `CHANGELOG.md` has a dated section for this version (not only `[Unreleased]`).
- [ ] `python scripts/generate_api_docs.py` run and `docs/api.md` committed if changed.

## 4. Tag (explicit approval required)

Only after **Test** and **Build** succeed and a maintainer approves the version:

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

- [ ] Tag name matches `__version__` (with `v` prefix).
- [ ] GitHub Release notes copied from `CHANGELOG.md` for that version.

Automated Cursor/Codex agents: **do not create tags** unless explicitly instructed.

## 5. Publish to PyPI (explicit approval required)

Publishing is **manual**. A maintainer must explicitly approve upload.

```bash
# TestPyPI (optional dry run)
python -m pip install twine
twine upload --repository testpypi dist/*

# Production (only after approval)
twine upload dist/*
```

- [ ] Credentials configured via trusted publishing or API token (never commit secrets).
- [ ] Version on PyPI matches git tag and `__version__`.
- [ ] README and metadata on PyPI match `pyproject.toml`.

Automated agents: **do not run `twine upload`** or mutate any package registry.

## Quick reference

| Step | Command / artifact | Agent allowed? |
|------|-------------------|----------------|
| Test | `pip install -e ".[dev]"`, `pytest`, examples | Yes |
| Build | `python -m build` | Yes (local only) |
| Docs | `python scripts/generate_api_docs.py` | Yes |
| Tag | `git tag`, `git push --tags` | No (unless asked) |
| Publish | `twine upload` | No (unless asked) |
