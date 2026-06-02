# HM-Arch

Python SDK for human-like agent memory: add, search, decay, consolidate, and inspect stats. The MVP runs fully offline — SQLite is the source of truth and vector search uses a deterministic local fallback (no API keys required for tests or demos).

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended for development) or `pip`

## Quick start

Clone the repository, install the package, and run the smoke tests:

```bash
git clone <repo-url> hm-arch && cd hm-arch
uv sync
uv run python -c "import hm_arch; print(hm_arch.__version__)"
uv run pytest
```

Without uv, use an editable install and pytest from your environment:

```bash
python -m pip install -e .
python -m pip install pytest
pytest
```

## MVP demo (end to end)

These examples use in-memory or temporary databases and need no external services:

```bash
uv run python examples/basic_usage.py
uv run python examples/agent_integration.py
```

Minimal API usage (matches `docs/spec.md`):

```python
from hm_arch import HMArch, EventType

memory = HMArch(db_path=":memory:")
memory.add("用户偏好 Python", event_type=EventType.CONVERSATION)
results = memory.search("用户喜欢什么语言", top_k=5)
report = memory.consolidate()
curve = memory.get_retention_curve(layer=2)
stats = memory.get_stats()
memory.close()
```

Prefer the context manager so the database is closed reliably:

```python
with HMArch(db_path="./.agent_memory.db") as memory:
  memory.add("User prefers concise PR descriptions", event_type=EventType.CONVERSATION)
  print(memory.search("PR style", top_k=3).results)
```

## Public API

Top-level exports from `hm_arch`:

| Symbol | Role |
|--------|------|
| `HMArch` | Facade: `add`, `search`, `consolidate`, `get_retention_curve`, `get_stats`, `context` |
| `MemoryConfig` | Settings and presets: `code_agent`, `chat_agent`, `research_agent` |
| `EventType` | Event classification enum |
| `MemoryReceipt`, `SearchResult`, `MemoryItem` | Add/search payloads |
| `ConsolidationReport`, `RetentionCurve`, `MemoryStats` | Consolidation, forgetting, and stats |

Authoritative contract: [`docs/spec.md`](docs/spec.md).

## Testing

Full offline suite (565+ tests at time of HM-12):

```bash
uv run pytest
# verbose: uv run pytest -v
# single file: uv run pytest tests/test_core.py
```

Issue acceptance command (pip-only environments):

```bash
python -m pip install -e . && pytest && python examples/basic_usage.py
```

## Project layout

```text
src/hm_arch/          # SDK implementation
tests/                # Offline pytest suite
examples/             # Runnable demos
docs/spec.md          # MVP product spec
docs/tasks.md         # Milestone breakdown (mirrors Linear)
```

## Development notes

- Runtime dependencies are empty; dev tools (`pytest`) are in `[dependency-groups] dev` and managed by uv.
- Consolidation uses a pattern-based semantic extractor — no LLM key is required.
- L4–L6 layers and PyPI publishing are out of scope for the MVP.
