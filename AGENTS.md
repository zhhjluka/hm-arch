# AGENTS.md

Guidance for AI agents working in **memashuman** (`create a human-like memory for agent`).

## Repository status

The repo includes a minimal `pyproject.toml` for **[uv](https://docs.astral.sh/uv/)**-managed Python. Application source, tests, and runtime services are not implemented yet.

## Tech stack

- **Language:** Python 3.12+
- **Environment / packages:** [uv](https://docs.astral.sh/uv/) (`uv sync`, `uv run`, `uv add`)
- **Layout:** Single package/repo (not a monorepo)

## Development commands

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if needed, then from the repo root:

```bash
uv sync                    # create/update .venv and install deps from uv.lock
uv run python -c "..."     # run commands in the project environment
uv add <package>           # add a runtime dependency
uv add --dev <package>     # add a dev dependency (dependency group)
uv run pytest              # run tests once added
uv run ruff check .        # run linters once configured
```

Pin the interpreter with `.python-version` (currently `3.12`). The virtualenv lives at `.venv/` (gitignored).

## Services

No services are required today. Document future memory backends (vector DB, Redis, etc.) in `README.md` when added.

## Cursor Cloud specific instructions

- **Update script:** `uv sync` (requires `pyproject.toml` and committed `uv.lock`).
- **PATH:** Ensure `~/.local/bin` is on `PATH` so `uv` is available (official installer: `curl -LsSf https://astral.sh/uv/install.sh | sh`).
- **Empty app:** Lint, test, and app `run` commands are N/A until source and tooling are added.
- **No blocking secrets** for the current tree.
