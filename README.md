# HM-Arch

Python SDK for human-like agent memory: add, search, decay, consolidate, and inspect stats. Designed for coding agents with offline-first defaults (SQLite + deterministic local vector fallback; no API keys required for tests or demos).

## Requirements

- Python 3.10+

## Quick start

From a fresh clone:

```bash
python -m pip install -e .
```

```python
from hm_arch import HMArch, EventType

memory = HMArch(db_path="./.agent_memory.db")
memory.add("用户偏好 Python", event_type=EventType.CONVERSATION)
results = memory.search("用户喜欢什么语言", top_k=5)
report = memory.consolidate()
memory.close()
```

Use a context manager to close the database automatically:

```python
with HMArch(db_path=":memory:") as memory:
    memory.add("Python is great")
    print(memory.search("Python", top_k=3).results)
```

## Setup and testing

Install the package in editable mode with dev dependencies, then run the full verification suite (matches the HM-12 / release acceptance command):

```bash
python -m pip install -e ".[dev]"
pytest
python examples/basic_usage.py
python examples/release_smoke.py
python examples/agent_integration.py
```

Runtime-only install (no pytest):

```bash
python -m pip install -e .
```

### Development with uv

This repo also supports [uv](https://docs.astral.sh/uv/) for a locked dev environment:

```bash
uv sync
uv run pytest
uv run python examples/basic_usage.py
uv run python examples/codex_hooks/demo.py
uv run python examples/claude_code_hooks/demo.py
```

## Examples

| Script | Purpose |
|--------|---------|
| `examples/basic_usage.py` | Add/search workflow (offline, in-memory DB) |
| `examples/agent_integration.py` | Context manager, stats, consolidation |
| `examples/import_package.py` | Minimal import smoke check |
| `examples/release_smoke.py` | Public API smoke test (pre-release checklist) |
| `examples/codex_hooks/` | Codex CLI turn-start, turn-end, idle consolidation hooks |
| `examples/claude_code_hooks/` | Claude Code hook equivalents (offline demos) |

## Agent hook integration

HM-Arch ships **portable hook examples** for coding agents. They run fully offline and do not install themselves into Codex or Claude Code — copy the patterns into your own `.codex/hooks.json` or `.claude/settings.json` when ready.

| Concern | Codex | Claude Code |
|---------|-------|-------------|
| Turn-start context injection | `examples/codex_hooks/turn_start.py` → `UserPromptSubmit` | `examples/claude_code_hooks/turn_start.py` → `UserPromptSubmit` |
| Turn-end conversation recording | `examples/codex_hooks/turn_end.py` → `Stop` | `examples/claude_code_hooks/turn_end.py` → `Stop` |
| Idle consolidation | `examples/codex_hooks/idle_consolidate.py` | `examples/claude_code_hooks/idle_consolidate.py` → `TeammateIdle` |

Set `HM_ARCH_DB_PATH` to choose the SQLite file (defaults to `./.hm_arch_agent_memory.db` under the process working directory — no home-directory paths).

```bash
uv run pytest tests/test_agent_hooks.py
uv run python examples/codex_hooks/demo.py
uv run python examples/claude_code_hooks/demo.py
```

See `examples/codex_hooks/README.md` and `examples/claude_code_hooks/README.md` for sample hook JSON fragments.

## Public API

The facade is `HMArch` with methods: `add()`, `search()`, `consolidate()`, `get_retention_curve()`, `get_stats()`, and `context()`. Types and config presets are exported from the top-level package:

```python
from hm_arch import (
    HMArch,
    MemoryConfig,
    EventType,
    MemoryReceipt,
    SearchResult,
    MemoryItem,
    ConsolidationReport,
    RetentionCurve,
    MemoryStats,
)
```

See [docs/api.md](docs/api.md) for the full public API reference (methods, dataclasses, config, and layers).
Regenerate after API changes: `python scripts/generate_api_docs.py`.

See `docs/spec.md` for the product specification.

## Release documentation

| Document | Purpose |
|----------|---------|
| [CHANGELOG.md](CHANGELOG.md) | Version history |
| [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) | Test, build, tag, and publish steps (PyPI requires explicit approval) |
| [docs/VERSIONING.md](docs/VERSIONING.md) | How to bump `src/hm_arch/_version.py` |

## Project layout

```text
src/hm_arch/          SDK source
tests/                Pytest suite (offline)
examples/             Runnable demos
docs/api.md           Public API reference
docs/spec.md          Product and API spec
docs/tasks.md         Milestone breakdown
```

## License

See [LICENSE](LICENSE).
