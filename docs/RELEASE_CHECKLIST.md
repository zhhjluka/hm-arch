# Release checklist

Use this checklist for each HM-Arch release. HM-Arch releases are distributed
through GitHub Releases only. **Git tags and GitHub Releases require explicit
human approval**; HM-Arch is not published to PyPI.

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

Do not upload these artifacts to a package registry.

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

## 5. Publish GitHub Release (explicit approval required)

After the tag is pushed, create a GitHub Release for the same version:

- [ ] Release title and tag match `vX.Y.Z`.
- [ ] Release notes are copied from the matching `CHANGELOG.md` section.
- [ ] Verified wheel and sdist artifacts from `dist/` are attached.
- [ ] Known limitations and optional backend requirements are documented.
- [ ] No package registry upload is performed.

## Quick reference

| Step | Command / artifact | Agent allowed? |
|------|-------------------|----------------|
| Test | `pip install -e ".[dev]"`, `pytest`, examples | Yes |
| Build | `python -m build` | Yes (local only) |
| Docs | `python scripts/generate_api_docs.py` | Yes |
| Tag | `git tag`, `git push --tags` | No (unless asked) |
| GitHub Release | Release notes plus `dist/` artifacts | No (unless asked) |
