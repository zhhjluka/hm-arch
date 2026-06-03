# HM-Arch v1.0.0

HM-Arch **1.0.0** is distributed through this GitHub Release only. It is **not** published to PyPI or any other package registry.

## Install from release artifacts

Download `hm_arch-1.0.0-py3-none-any.whl` and/or `hm_arch-1.0.0.tar.gz` from the release assets, then install in a virtual environment (Python >= 3.10):

```bash
python3 --version   # requires Python >= 3.10
python3 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install /path/to/hm_arch-1.0.0-py3-none-any.whl
python -c "import hm_arch; print(hm_arch.__version__)"
python examples/release_smoke.py
```

Optional ChromaDB support (not required for offline use):

```bash
python -m pip install '/path/to/hm_arch-1.0.0-py3-none-any.whl[chroma]'
```

For development from source (before or without a published release):

```bash
git clone https://github.com/ZhangHangjianMA/memashuman.git
cd memashuman
python3 -m pip install -e ".[dev]"
```

## What's included

### Memory layers (L0–L6)

| Layer | Role |
|-------|------|
| L0 | Sensory register (in-memory) |
| L1 | Working memory (in-memory, session-scoped) |
| L2 | Episodic buffer (SQLite + vector index) |
| L3 | Semantic memory (SQLite triples + vector index) |
| L4 | Long-term gzip archive |
| L5 | Procedural / skills memory |
| L6 | Meta-memory and strategy hints |

All layers are reachable through the `HMArch` facade with accurate cross-layer statistics.

### Public API (`HMArch`)

- `add()`, `search()`, `forget()`, `consolidate()`, `get_retention_curve()`, `get_stats()`
- `context()` / `agent_context()` for agent session load/save
- `MemoryConfig` presets: `code_agent`, `chat_agent`, `research_agent`
- Offline-first defaults: no API keys, network, or ChromaDB required for core behavior

### Optional backends

| Backend | Purpose | Requirement |
|---------|---------|-------------|
| **Local (default)** | Deterministic token-overlap vectors and rule-based semantic extraction | None |
| **OpenAI** | LLM scoring and extraction | `enable_llm_providers=True`, API key |
| **DeepSeek** | LLM scoring and extraction | `enable_llm_providers=True`, API key |
| **ChromaDB** | Persistent vector store | `chromadb>=0.5.0`, `vector_backend="chroma"` (from source: `pip install -e '.[chroma]'`; from this release wheel: `pip install '/path/to/hm_arch-1.0.0-py3-none-any.whl[chroma]'`) |

When `provider_fallback_to_local=True` (the default), missing optional dependencies, credentials, or runtime provider failures use local deterministic behavior (tests and demos run fully offline). With `provider_fallback_to_local=False`, those conditions raise actionable errors.

### Agent integration examples

- `examples/codex_hooks/` — Codex CLI turn-start, turn-end, idle consolidation
- `examples/claude_code_hooks/` — Claude Code equivalents (offline demos)

Set `HM_ARCH_DB_PATH` to choose the SQLite database file.

## Benchmark evidence (HM-31)

Reproducible PRD benchmarks validate single-process, local-fallback operation. See https://github.com/ZhangHangjianMA/memashuman/blob/v1.0.0/docs/benchmarks.md

Example observed results (Linux, Python 3.12, local fallback, 2026-06-03):

| Metric | Observed | PRD test limit |
|--------|----------|----------------|
| `add()` p95 | ~3.8 ms | < 50 ms |
| `search()` p95 @ 10k L2 | ~73 ms | < 100 ms |
| `consolidate()` @ 10k L2 | ~0.9 s | < 60 s |
| SQLite storage (10k L2 + 5k L3) | ~8.5 MB | < 500 MB |
| 7-day L3 semantic accuracy | 100% | > 80% |

Run on your hardware:

```bash
uv run pytest tests/prd_benchmarks -m benchmark -v
uv run python scripts/run_prd_benchmarks.py
```

## Known limitations

- **Not on PyPI** — install from GitHub Release artifacts or source only.
- **No MCP server** — SDK library only; MCP tooling remains out of scope.
- **Single-process, single-agent** — no multi-user sharing, encryption, or distributed storage.
- **L4 archive PRD formula deviation** — uniform 30-day-old L2 rows typically do not archive because modeled retention (~0.26) stays above `l2_archive_threshold` (0.15). Mixed-age and agent-simulation scenarios are documented at https://github.com/ZhangHangjianMA/memashuman/blob/v1.0.0/docs/benchmarks.md
- **Week 9 stretch targets** — reported for information only; they do not gate benchmark acceptance.
- **Optional backends** — OpenAI, DeepSeek, and Chroma require extra packages and credentials; with `provider_fallback_to_local=True` (default), missing pieces use the offline path.

## Verification (maintainers)

Before tagging `v1.0.0` (Python >= 3.10):

```bash
uv run pytest && uv run python examples/release_smoke.py
python3 --version
uv run --with build python -m build --outdir dist
# Clean wheel + sdist install — see https://github.com/ZhangHangjianMA/memashuman/blob/v1.0.0/docs/RELEASE_CHECKLIST.md
```

Full checklist: https://github.com/ZhangHangjianMA/memashuman/blob/v1.0.0/docs/RELEASE_CHECKLIST.md

## Full changelog

https://github.com/ZhangHangjianMA/memashuman/blob/v1.0.0/CHANGELOG.md#100---2026-06-03
