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

Cross-platform release artifacts and npm binary distribution are handled in
MEM-62.
