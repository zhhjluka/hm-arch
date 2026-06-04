# Versioning strategy

HM-Arch follows [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`).

## Single source of truth

The release version lives in one file:

```text
src/hm_arch/_version.py   →   __version__
```

`pyproject.toml` reads it dynamically via setuptools (`hm_arch._version.__version__`).
`hm_arch.__version__` re-exports the same value for runtime checks.

## When to bump

| Change | Bump |
|--------|------|
| Breaking public API or schema incompatible with prior DBs | **MAJOR** |
| New features, layers, or config fields (backward compatible) | **MINOR** |
| Bug fixes, docs, tests, internal refactors | **PATCH** |

Pre-1.0 releases used `0.MINOR.PATCH`. From **1.0.0** onward, follow semver for public API changes.

## Distribution channels

HM-Arch may be published through multiple channels. Each channel uses the **same**
semver string derived from `__version__` (Git tag: `vX.Y.Z`; PyPI and npm:
`X.Y.Z` without the `v` prefix).

| Channel | Artifact / package | First planned use | Notes |
|---------|-------------------|-------------------|-------|
| GitHub Releases | wheel, sdist, release notes | v1.0.0 (current) | Primary distribution today; always attach verified `dist/` artifacts |
| PyPI | `hm-arch` | v1.1.0+ | `pip install hm-arch`, `pipx install hm-arch` after maintainer-approved publish |
| npm | `@hm-arch/installer` | v1.2.0+ | Installer/launcher only; pairs with a compatible `hm-arch` PyPI version |

Historical note: **v1.0.0** was released on GitHub only. Registry publication is
planned but not required for every release until the integration roadmap milestone
for that channel is reached.

## Version coordination across channels

When more than one channel is used for a release, keep versions aligned:

1. Bump `src/hm_arch/_version.py` once per release.
2. Build wheel and sdist locally; verify installs (see [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)).
3. Create Git tag `vX.Y.Z` and GitHub Release `vX.Y.Z` with matching artifacts.
4. If PyPI publication is in scope for this release, upload the **same** wheel/sdist
   built for GitHub (or rebuild from the tagged commit and confirm `__version__`
   matches) so `pip install hm-arch==X.Y.Z` matches the GitHub Release.
5. If an npm release is in scope, publish `@hm-arch/installer@X.Y.Z` (or the
   documented pairing version) that installs or references the matching `hm-arch`
   Python package version documented in the release notes.

Do not publish a higher version to one channel and leave another channel on an
older version without an explicit decision recorded in release notes.

## Maintainer approval and automated agents

These actions require **explicit maintainer approval** before execution:

- Creating or pushing a Git release tag
- Creating or editing a GitHub Release (including attaching artifacts)
- Uploading to PyPI or TestPyPI
- Publishing to the npm registry

Automated agents (Cursor, Codex, CI bots) may run tests, local builds, doc
generation, and install verification in isolated environments. They must **not**
create tags, publish GitHub Releases, or upload to PyPI or npm unless a maintainer
explicitly instructs them to do so for a specific version.

## Release bump checklist

1. Decide the next version from the table above.
2. Edit `src/hm_arch/_version.py` (`__version__`).
3. Add a dated section to `CHANGELOG.md` (move items out of `[Unreleased]`).
4. Regenerate API docs: `python scripts/generate_api_docs.py`
5. Run release verification (see [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)).
6. Commit with message like `chore: release v0.1.1`.
7. After maintainer approval: tag, GitHub Release, and any approved registry
   uploads for that version.
