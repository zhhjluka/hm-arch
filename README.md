# HM-Arch

Python SDK for human-like agent memory: add, search, decay, consolidate, and inspect stats. Designed for coding agents with offline-first defaults (SQLite + deterministic local vector fallback; no API keys required for tests or demos).

**Prepared version:** `1.0.0` (GitHub Release pending maintainer approval — not published to PyPI).

## Requirements

- Python 3.10+

## Quick start

### From a GitHub Release (wheel, after publication)

Once the `v1.0.0` GitHub Release is published, download `hm_arch-1.0.0-py3-none-any.whl` from
[github.com/ZhangHangjianMA/memashuman/releases](https://github.com/ZhangHangjianMA/memashuman/releases), then:

```bash
python3.12 -m venv .venv && source .venv/bin/activate   # Python 3.10+ required
python -m pip install --upgrade pip
python -m pip install /path/to/hm_arch-1.0.0-py3-none-any.whl
```

Until that release exists, install from source (below) or build a wheel locally per
[docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md).

### From source (development)

```bash
git clone https://github.com/ZhangHangjianMA/memashuman.git
cd memashuman
python -m pip install -e .
```

```python
from hm_arch import HMArch, EventType

memory = HMArch(db_path="./.agent_memory.db")
memory.add("用户偏好 Python", event_type=EventType.CONVERSATION)
results = memory.search("用户喜欢什么语言")
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
uv run pytest tests/prd_benchmarks -m benchmark -v   # optional PRD scale benchmarks
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

The facade is `HMArch` with methods: `add()`, `search()`, `forget()`, `consolidate()`, `get_retention_curve()`, `get_stats()`, `context()`, and `agent_context()`. Types and config presets are exported from the top-level package:

```python
from hm_arch import (
    HMArch,
    AgentContext,
    MemoryConfig,
    EventType,
    MemoryReceipt,
    SearchResult,
    MemoryItem,
    ConsolidationReport,
    RetentionCurve,
    MemoryStats,
    ForgetResult,
)
```

Phase 3 public contract (see `docs/spec.md`):

- `add()` defaults to `EventType.CONVERSATION`; L1 and L2 share the same `memory_id`.
- `search()` defaults to `top_k=10` and `min_retention=0.1`; supports `layer_filter`.
- `forget(memory_id=None, force=False)` returns `ForgetResult` and clears searchable layers.
- `get_retention_curve(memory_id, days_ahead=90)` or `get_retention_curve(layer=2)`.
- `with memory.context() as ctx:` yields `AgentContext` with `load_session()` / `save_session()`.

See [docs/api.md](docs/api.md) for the full public API reference (methods, dataclasses, config, and layers).
Regenerate after API changes: `python scripts/generate_api_docs.py`.

See `docs/spec.md` for the product specification.

PRD scale and performance benchmarks (10k L2, latency p95, storage, 7-day scenario) are
documented in [docs/benchmarks.md](docs/benchmarks.md). They are excluded from default
`pytest` via the `benchmark` marker.

## Optional backends

| Backend | When to use | Setup |
|---------|-------------|-------|
| Local (default) | Offline tests, demos, CI | None |
| OpenAI / DeepSeek | LLM scoring and semantic extraction | `MemoryConfig(enable_llm_providers=True)` + API key |
| ChromaDB | Persistent vector index | From source: `pip install -e ".[chroma]"`. From a published release wheel: `pip install /path/to/hm_arch-*.whl chromadb`. Then `vector_backend="chroma"`. |

When `provider_fallback_to_local=True` (the default), missing optional dependencies or
credentials use local deterministic behavior. With `provider_fallback_to_local=False`,
misconfiguration or provider failures raise actionable errors instead.

## Release documentation

| Document | Purpose |
|----------|---------|
| [CHANGELOG.md](CHANGELOG.md) | Version history |
| [docs/RELEASE_NOTES_v1.0.0.md](docs/RELEASE_NOTES_v1.0.0.md) | Draft GitHub Release notes for v1.0.0 |
| [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) | Test, build, tag, and GitHub Release steps |
| [docs/VERSIONING.md](docs/VERSIONING.md) | How to bump `src/hm_arch/_version.py` |

HM-Arch is distributed via **GitHub Releases** (wheel/sdist artifacts). There is no `pip install hm-arch` from PyPI.

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
