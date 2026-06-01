# HM-Arch

Python SDK scaffold for human-like agent memory.

## Development

This project uses uv for development and test dependencies. Create the uv-managed environment, verify the package import, and run the smoke tests:

```bash
uv sync
uv run python -c "import hm_arch"
uv run pytest
```

Runtime dependencies remain empty; `python -m pip install -e .` is enough for runtime imports, while tests run through uv.
