# HM-Arch standalone executable

MEM-61 packages the `hm-arch` CLI as a single-file executable using
[PyInstaller](https://pyinstaller.org/). The binary bundles the Python runtime
and the `hm_arch` package so agent hooks can run without a system Python
interpreter.

## Build (local)

```bash
uv sync
uv run python scripts/build_standalone.py --clean
```

Output: `dist/standalone/hm-arch` (or `hm-arch.exe` on Windows).

## Verify

```bash
./dist/standalone/hm-arch --help
pytest tests/test_standalone_executable.py -q
```

The smoke tests also compare recall output between the frozen binary and
`python -m hm_arch.integrations.cli`.

## Layout

| Path | Purpose |
|------|---------|
| `packaging/cli_entrypoint.py` | PyInstaller entry script |
| `packaging/hm-arch.spec` | PyInstaller build spec |
| `scripts/build_standalone.py` | Local build helper |
| `dist/standalone/hm-arch` | Built executable (gitignored) |
| `dist/release/` | Versioned release artifacts (gitignored) |
| `scripts/prepare_release_artifacts.py` | Version, checksum, and metadata helper |
| `scripts/validate_release_artifacts.py` | Checksum/metadata validation |
| `scripts/smoke_standalone_artifact.py` | CI-friendly artifact smoke test |

## Release artifacts (MEM-62)

CI builds supported standalone executables on macOS, Linux, and Windows via
[`.github/workflows/standalone-release-build.yml`](../.github/workflows/standalone-release-build.yml).

Supported targets:

| OS | Architectures |
|----|----------------|
| linux | `x86_64`, `aarch64` |
| darwin | `arm64` |
| windows | `x86_64` |

Artifact naming:

```text
hm-arch-{version}-{os}-{arch}[.exe]
```

Example: `hm-arch-1.0.0-linux-x86_64`, `hm-arch-1.0.0-windows-x86_64.exe`.

### Prepare locally

```bash
uv sync
uv run python scripts/build_standalone.py --clean
uv run python scripts/prepare_release_artifacts.py
```

This writes:

- versioned executable under `dist/release/`
- per-artifact `*.sha256` checksum file
- `hm-arch-{version}-standalone-release-metadata.json`

Validate checksums and metadata:

```bash
uv run python scripts/validate_release_artifacts.py --artifacts-dir dist/release
uv run python scripts/smoke_standalone_artifact.py dist/release/hm-arch-*
```

Offline tests:

```bash
uv run pytest tests/test_release_artifacts.py tests/test_standalone_executable.py -q
```

The npm installer (`@hm-arch/installer`) downloads and verifies release artifacts
for supported platforms. See [npm-installer.md](npm-installer.md).
