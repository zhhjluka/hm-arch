# PyPI clean-install verification (maintainers)

Reproducible steps to verify `hm-arch` installs correctly **before** any PyPI
upload. Use a locally built wheel or sdist from the tagged commit (see
[RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) section 2).

**Do not upload to PyPI or TestPyPI** unless a maintainer has explicitly approved
publication for that version.

**Python:** 3.10 or newer. System `python3` may be older; use `python3.12` or an
explicit 3.10+ binary.

## Prerequisites

Build artifacts from the release commit:

```bash
cd /path/to/hm-arch
python3.12 --version   # must be >= 3.10
python3.12 -m pip install -U pip build
python3.12 -m build --outdir dist
ls dist/hm_arch-*.whl dist/hm_arch-*.tar.gz
```

Record the version in the filenames (for this release, `2.0.0`).

## 1. Clean `pip` install (isolated venv)

```bash
export HM_ARCH_VERSION=2.0.0   # match dist/ artifact version
rm -rf /tmp/hm-arch-pip-verify
python3.12 -m venv /tmp/hm-arch-pip-verify
/tmp/hm-arch-pip-verify/bin/pip install --upgrade pip
/tmp/hm-arch-pip-verify/bin/pip install "dist/hm_arch-${HM_ARCH_VERSION}-py3-none-any.whl"
```

Verify import, CLI, and release smoke:

```bash
/tmp/hm-arch-pip-verify/bin/python -c "import hm_arch; assert hm_arch.__version__ == '${HM_ARCH_VERSION}'"
/tmp/hm-arch-pip-verify/bin/hm-arch --help
/tmp/hm-arch-pip-verify/bin/python /path/to/hm-arch/examples/release_smoke.py
```

Expected: `hm-arch --help` lists `recall`, `record`, `consolidate`, `codex`,
`claude-code`, `install`, `uninstall`, `status`, and `doctor`. Release smoke
prints `Release smoke test passed.`

### Post-PyPI publish (maintainer only)

After maintainer-approved `twine upload`, repeat in a **new** venv without local
`dist/`:

```bash
rm -rf /tmp/hm-arch-pypi-verify
python3.12 -m venv /tmp/hm-arch-pypi-verify
/tmp/hm-arch-pypi-verify/bin/pip install --upgrade pip
/tmp/hm-arch-pypi-verify/bin/pip install "hm-arch==${HM_ARCH_VERSION}"
/tmp/hm-arch-pypi-verify/bin/python -c "import hm_arch; print(hm_arch.__version__)"
/tmp/hm-arch-pypi-verify/bin/hm-arch --help
```

## 2. Clean `pipx` install (isolated application)

`pipx` installs the `hm-arch` console script into an isolated environment. Use a
dedicated `PIPX_HOME` and `PIPX_BIN_DIR` so verification does not touch the user
default.

```bash
export HM_ARCH_VERSION=2.0.0
export PIPX_HOME=/tmp/hm-arch-pipx-home
export PIPX_BIN_DIR=/tmp/hm-arch-pipx-bin
rm -rf "$PIPX_HOME" "$PIPX_BIN_DIR"
mkdir -p "$PIPX_BIN_DIR"

# Install pipx if needed: python3.12 -m pip install pipx
pipx install --force "dist/hm_arch-${HM_ARCH_VERSION}-py3-none-any.whl"
```

Verify CLI and a management command:

```bash
"$PIPX_BIN_DIR/hm-arch" --help
cd /tmp && "$PIPX_BIN_DIR/hm-arch" status codex
```

Expected: `status codex` reports `not_installed` (or similar) when hooks are not
present — that confirms the CLI runs from the pipx environment.

Clean up:

```bash
pipx uninstall hm-arch
```

### Post-PyPI publish (maintainer only)

```bash
export PIPX_HOME=/tmp/hm-arch-pipx-pypi
export PIPX_BIN_DIR=/tmp/hm-arch-pipx-pypi-bin
rm -rf "$PIPX_HOME" "$PIPX_BIN_DIR"
mkdir -p "$PIPX_BIN_DIR"
pipx install --force "hm-arch==${HM_ARCH_VERSION}"
"$PIPX_BIN_DIR/hm-arch" --help
pipx uninstall hm-arch
```

## 3. Integration CLI smoke (pip-installed `hm-arch`)

After a successful pip install, confirm Codex hook installation works from a
throwaway project directory:

```bash
export PATH="/tmp/hm-arch-pip-verify/bin:$PATH"
mkdir -p /tmp/hm-arch-smoke-codex && cd /tmp/hm-arch-smoke-codex
rm -rf .codex
hm-arch install codex
hm-arch status codex
hm-arch doctor codex
hm-arch uninstall codex
```

Full three-agent manual steps: [integration-cli-smoke.md](integration-cli-smoke.md)
and per-agent guides under [agents/](agents/).

## 4. Optional: clean sdist install

Use a **separate** venv from the wheel check:

```bash
rm -rf /tmp/hm-arch-sdist-verify
python3.12 -m venv /tmp/hm-arch-sdist-verify
/tmp/hm-arch-sdist-verify/bin/pip install --upgrade pip build
/tmp/hm-arch-sdist-verify/bin/pip install "dist/hm_arch-${HM_ARCH_VERSION}.tar.gz"
/tmp/hm-arch-sdist-verify/bin/python -c "import hm_arch; assert hm_arch.__version__ == '${HM_ARCH_VERSION}'"
```

## Checklist summary

| Check | Pass criterion |
|-------|----------------|
| Wheel `pip install` | `import hm_arch`, version matches |
| `hm-arch --help` | All subcommands listed |
| `release_smoke.py` | Prints `Release smoke test passed.` |
| `pipx install` | `hm-arch` on `PIPX_BIN_DIR` runs |
| `hm-arch install codex` | Creates `.codex/hooks.json` with three HM-Arch hooks |
| PyPI `pip install hm-arch==X.Y.Z` | Maintainer-only, after approved upload |

Automated offline tests (repository clone, editable install):

```bash
pytest tests/test_integrations_cli_manage.py tests/test_codex_installer.py tests/test_claude_code_installer.py -q
```
