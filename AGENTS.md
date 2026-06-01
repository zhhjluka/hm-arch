# AGENTS.md

Guidance for AI agents working in **memashuman** (`create a human-like memory for agent`).

## Repository status

As of the initial commit, this repository contains only `README.md`, `LICENSE`, and a Python-oriented `.gitignore`. There is **no application source**, dependency manifest (`pyproject.toml`, `requirements.txt`), tests, Docker setup, or CI configuration yet.

## Tech stack (inferred)

- **Language:** Python (from `.gitignore` template and project description)
- **Layout:** Single package/repo (not a monorepo)

When implementation lands, prefer standard Python packaging (`pyproject.toml`) and document run commands here.

## Development commands

Until a manifest and entrypoint exist, there are no project-specific lint, test, or run scripts. Use the system or virtualenv Python:

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
```

After `requirements.txt` or `pyproject.toml` is added:

```bash
pip install -r requirements.txt          # if requirements.txt exists
pip install -e ".[dev]"                  # if pyproject.toml defines extras
pytest                                   # if tests are added
ruff check .                             # if ruff is configured
```

## Services

No services are required today. Future memory backends (vector DB, Redis, etc.) should be documented in `README.md` and this file when added.

## Cursor Cloud specific instructions

- **Update script:** On VM startup, dependency install runs only when `requirements.txt` or `pyproject.toml` exists (see environment update script). No services are started automatically.
- **Empty repo:** Lint, test, and `run dev` are N/A until code and manifests are committed. Agents should not assume Redis, Celery, Django, or other entries in `.gitignore` apply to this project—they come from the default Python gitignore template.
- **Virtualenv:** Use `.venv` at the repo root (`python3 -m venv .venv && source .venv/bin/activate`). It is gitignored. On Debian/Ubuntu without `ensurepip`, install `python3.12-venv` once before creating `.venv`.
- **No blocking secrets** for the current tree.
