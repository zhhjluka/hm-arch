<p align="center">
  <img src="docs/assets/hm-arch-logo.png" alt="HM-Arch - Human-like Memory for AI Agents" width="760">
</p>

<p align="center">
  <strong>Human-like memory architecture for AI agents.</strong><br>
  Store experiences, retrieve useful context, forget safely, and consolidate knowledge over time.
</p>

<p align="center">
  <a href="https://github.com/ZhangHangjianMA/memashuman/releases/tag/v1.0.0"><img src="https://img.shields.io/badge/release-v1.0.0-111111" alt="GitHub Release v1.0.0"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-3776AB" alt="Python 3.10+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-4C9A7D" alt="Apache-2.0 License"></a>
  <a href="https://github.com/ZhangHangjianMA/memashuman/actions"><img src="https://img.shields.io/badge/tests-778%20passing-4C9A7D" alt="778 tests passing"></a>
</p>

---

HM-Arch is an offline-first Python SDK that gives agents a layered memory system inspired by human memory. It combines short-lived working context, durable episodic and semantic memory, long-term archives, procedural skills, meta-memory, retention decay, and automatic consolidation behind one `HMArch` facade.

Core behavior runs locally with SQLite and deterministic retrieval. No API keys, network access, or external services are required for tests, demos, or the default runtime.

## Why HM-Arch?

Most agent memory systems focus on storing and retrieving text. HM-Arch also models what happens after storage:

- **Layered memory, L0-L6**: sensory, working, episodic, semantic, archive, procedural, and meta-memory.
- **Retention-aware retrieval**: rank results using relevance, retention, and layer priority.
- **Human-like forgetting**: decay, review scheduling, safe deletion windows, and explicit `forget()`.
- **Automatic consolidation**: extract semantics, merge duplicates, resolve conflicts, archive old memories, and schedule reviews.
- **Agent-ready integration**: context APIs plus portable Codex and Claude Code hook examples.
- **Offline-first by default**: SQLite and local deterministic behavior, with optional OpenAI, DeepSeek, and ChromaDB backends.

## Quick Start

### Install

**Today (v1.0.0):** install from the [v1.0.0 GitHub Release](https://github.com/ZhangHangjianMA/memashuman/releases/tag/v1.0.0) wheel or sdist, or from source (below).

**Planned registries** (see [docs/agent-integration-roadmap.md](docs/agent-integration-roadmap.md)):

| Channel | Package | Target version | Maintainer approval |
|---------|---------|----------------|---------------------|
| GitHub Releases | wheel + sdist | every release | required for tag and release |
| PyPI | `hm-arch` | v1.1.0+ | required before first publish and each release |
| npm | `@hm-arch/installer` | v1.2.0+ | required before first publish and each release |

All public channels use the same semver from `src/hm_arch/_version.py`. Automated agents must not create tags, GitHub Releases, or registry uploads without explicit maintainer instruction. See [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) and [docs/VERSIONING.md](docs/VERSIONING.md).

#### Install from the GitHub Release (current)

Download `hm_arch-1.0.0-py3-none-any.whl` from the [v1.0.0 release page](https://github.com/ZhangHangjianMA/memashuman/releases/tag/v1.0.0), then install it in a Python 3.10+ environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install /path/to/hm_arch-1.0.0-py3-none-any.whl
```

For development from source:

```bash
git clone https://github.com/ZhangHangjianMA/memashuman.git
cd memashuman
python -m pip install -e ".[dev]"
```

After PyPI publication is approved (planned v1.1.0+):

```bash
pip install hm-arch
# or: pipx install hm-arch
```

### Add and Search Memories

```python
from hm_arch import EventType, HMArch

with HMArch(db_path="./.agent_memory.db") as memory:
    memory.add(
        "The user prefers concise Python code reviews",
        event_type=EventType.CONVERSATION,
        importance=0.9,
    )

    results = memory.search("How should I review this pull request?", top_k=3)

    for item in results.results:
        print(f"[L{item.layer}] {item.content} (score={item.score:.3f})")
```

### Consolidate Knowledge

```python
with HMArch(db_path="./.agent_memory.db") as memory:
    memory.add("The project uses Python 3.12 and pytest")
    report = memory.consolidate()

    print(report.extracted_semantics)
    print(memory.get_stats().by_layer)
```

## Memory Architecture

| Layer | Name | Role |
|------:|------|------|
| L0 | Sensory register | Captures the most recent signals in memory |
| L1 | Working memory | Holds session-scoped context |
| L2 | Episodic memory | Stores durable events and conversations |
| L3 | Semantic memory | Stores extracted facts and relationships |
| L4 | Long-term archive | Compresses low-retention memories |
| L5 | Procedural memory | Stores reusable skills and procedures |
| L6 | Meta-memory | Tracks strategies and memory-system knowledge |

The facade exposes the complete lifecycle:

```python
memory.add(...)
memory.search(...)
memory.forget(...)
memory.consolidate()
memory.get_retention_curve(...)
memory.get_stats()
```

See [docs/api.md](docs/api.md) for the full public API and [docs/spec.md](docs/spec.md) for the product contract.

## Agent Integration

HM-Arch includes portable hook examples for coding agents. They run fully offline and can be adapted to your own agent configuration.

| Workflow | Codex | Claude Code |
|----------|-------|-------------|
| Load relevant context before a turn | `examples/codex_hooks/turn_start.py` | `examples/claude_code_hooks/turn_start.py` |
| Record conversations after a turn | `examples/codex_hooks/turn_end.py` | `examples/claude_code_hooks/turn_end.py` |
| Consolidate during idle time | `examples/codex_hooks/idle_consolidate.py` | `examples/claude_code_hooks/idle_consolidate.py` |

```bash
uv run python examples/codex_hooks/demo.py
uv run python examples/claude_code_hooks/demo.py
```

Set `HM_ARCH_DB_PATH` to choose the agent memory database. See the hook-specific READMEs under `examples/` for configuration fragments.

## Optional Backends

The local path remains the default even when optional integrations are available.

| Backend | Purpose | Setup |
|---------|---------|-------|
| Local | Offline retrieval and semantic extraction | No dependencies or credentials |
| OpenAI / DeepSeek | LLM scoring and semantic extraction | `MemoryConfig(enable_llm_providers=True)` plus API key |
| ChromaDB | Persistent vector index | Install the release wheel with `[chroma]` or source with `.[chroma]` |

When `provider_fallback_to_local=True` (the default), missing credentials, dependencies, or provider failures fall back to deterministic local behavior.

## Benchmarks

HM-Arch includes reproducible PRD-scale benchmarks for latency, storage, consolidation, and long-running memory behavior.

```bash
uv run pytest tests/prd_benchmarks -m benchmark -v
uv run python scripts/run_prd_benchmarks.py
```

The benchmark suite covers 10k L2 memories, search and add latency p95, consolidation runtime, storage size, semantic accuracy, and 30-day archive scenarios. Results and known limitations are documented in [docs/benchmarks.md](docs/benchmarks.md).

## Development

```bash
uv sync
uv run pytest
uv run python examples/basic_usage.py
uv run python examples/agent_integration.py
uv run python examples/release_smoke.py
```

The default test suite runs fully offline. Benchmark tests are marked separately and excluded from normal `pytest` runs.

## Documentation

| Document | Purpose |
|----------|---------|
| [docs/api.md](docs/api.md) | Public API reference |
| [docs/spec.md](docs/spec.md) | Product and API contract |
| [docs/benchmarks.md](docs/benchmarks.md) | PRD benchmark results and limitations |
| [docs/RELEASE_NOTES_v1.0.0.md](docs/RELEASE_NOTES_v1.0.0.md) | v1.0.0 release notes |
| [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) | Release and registry publication policy |
| [docs/VERSIONING.md](docs/VERSIONING.md) | Semver and cross-channel version alignment |
| [docs/agent-integration-roadmap.md](docs/agent-integration-roadmap.md) | PyPI and npm integration timeline |
| [CHANGELOG.md](CHANGELOG.md) | Version history |

## Project Layout

```text
src/hm_arch/          SDK source
tests/                Offline test suite
tests/prd_benchmarks/ Scale and performance benchmarks
examples/             Runnable examples and agent hooks
docs/                 Specifications, API docs, and release notes
```

## License

HM-Arch is licensed under the [Apache License 2.0](LICENSE).
