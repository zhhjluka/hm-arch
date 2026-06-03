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

## Release bump checklist

1. Decide the next version from the table above.
2. Edit `src/hm_arch/_version.py` (`__version__`).
3. Add a dated section to `CHANGELOG.md` (move items out of `[Unreleased]`).
4. Regenerate API docs: `python scripts/generate_api_docs.py`
5. Run release verification (see [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)).
6. Commit with message like `chore: release v0.1.1`.
7. Tag and publish a GitHub Release only after explicit approval.

HM-Arch is not published to PyPI. Automated agents must not create tags or
GitHub Releases without explicit human approval.
