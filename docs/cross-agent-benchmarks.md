# Cross-agent memory benchmarks (HM-71 / MEM-68)

Reproducible harness for **LoCoMo**, **tau2-bench**, and **HotpotQA** across host
agents and memory providers. The PRD-scale HM-Arch benchmarks live in
[benchmarks.md](benchmarks.md); this document covers the cross-agent matrix.

## Goals

- One shared lifecycle for ingest → consolidate → query → evaluate
- Pluggable :class:`~benchmarks.cross_agent.protocol.MemoryBackend` and
  :class:`~benchmarks.cross_agent.protocol.AgentRunner` adapters
- Deterministic run identifiers and isolated per-run storage
- JSONL per-query streaming, CSV roll-up, and JSON summary output
- Checkpoint/resume between lifecycle phases and individual queries

## Registered providers

| Memory backend | Status in repo | Notes |
|----------------|----------------|-------|
| `no_memory` | Implemented | Empty-recall baseline |
| `hm_arch` | Implemented | SQLite-isolated HM-Arch adapter |
| `native_memory` | Stub | Register via `register_memory_backend()` |
| `openviking` | Stub | Register via `register_memory_backend()` |
| `mem0` | Stub | Register via `register_memory_backend()` |

| Agent | Status in repo | Notes |
|-------|----------------|-------|
| `openclaw` | Production CLI runner | Invokes `openclaw` boundary; use `use_mock_agent=True` for offline harness tests |
| `hermes` | Production CLI runner | Invokes `hermes` boundary with isolated `HERMES_HOME` |
| `claude_code` | Production CLI runner | Invokes `claude` boundary with isolated config dir |
| `codex` | Production CLI runner | Invokes `codex` boundary with isolated `CODEX_HOME` |

See [benchmark compatibility matrix](agents/benchmark-compatibility-matrix.md) for the full
agent × backend grid (`real`, `unsupported`, `mock_only`).

## Lifecycle phases

1. **setup** — create isolated storage directory, `backend.open()`
2. **ingest** — persist fixture corpus via `backend.ingest()`
3. **consolidate** — optional `backend.consolidate()` (family-dependent)
4. **query** — for each query: recall → agent answer → per-query metrics
5. **evaluate** — aggregate roll-up metrics (no external scorer required offline)
6. **checkpoint** — persist `checkpoint.json`, JSONL, CSV, and summary JSON
7. **teardown** — `backend.close()`

Synthetic fixtures in `benchmarks/cross_agent/fixtures/synthetic.py` exercise every
phase offline without API keys.

## Metric definitions and timing boundaries

| Metric | Definition | Timing boundary |
|--------|------------|-----------------|
| `accuracy` | `1.0` when normalized prediction equals normalized `expected_answer`, else `0.0`; `null` when no ground-truth answer | Computed after agent step |
| `task_success` | Agent-reported success for tau2-style tasks; `null` when not applicable | Agent step only |
| `retrieval_hit_rate` | Fraction of `expected_memory_ids` present in `retrieved_ids`; `null` when fixture provides none | Recall step only |
| `recall_time_ms` | Wall time inside `backend.recall()` | Recall start → recall return |
| `agent_time_ms` | Wall time inside `agent.answer()` | Agent start → agent return |
| `query_time_ms` | Wall time for recall **and** agent answer for one query | Before recall → after agent return |
| `input_tokens` | Whitespace token estimate of prompt passed to agent (offline approximation) | Agent step |
| `output_tokens` | Whitespace token estimate of agent answer | Agent step |
| `failure_count` | Sum of recall and agent failures for the query | Recall + agent steps |

## Result schema

Each run writes under ``<output-dir>/<run_id>/``:

- `queries.jsonl` — one JSON object per query (streamed during the run)
- `queries.csv` — tabular roll-up of all query metrics
- `summary.json` — run config, aggregates, environment metadata
- `storage/` — isolated backend state and `checkpoint.json`

`summary.json` aggregates:

- `mean_accuracy`, `task_success_rate`, `mean_retrieval_hit_rate`
- `mean_query_time_ms`, `total_input_tokens`, `total_output_tokens`
- `total_failure_count`

The per-query schema supports all three families:

- **LoCoMo** — conversational ingest + multi-session QA with `expected_memory_ids`
- **tau2-bench** — task logs with `task_success_criteria`
- **HotpotQA** — multi-document ingest + multi-hop QA with `supporting_facts`

## Deterministic run identifiers

When `run_id` is omitted, the harness derives:

```
sha256("{family}|{agent}|{backend}|{seed}")[:16]
```

prefixed as `{family}-{agent}-{backend}-s{seed}-<digest>`.

## Running

```bash
# Single synthetic run (default: LoCoMo + Codex + HM-Arch)
uv run python scripts/run_cross_agent_benchmark.py

# All three families
uv run python scripts/run_cross_agent_benchmark.py --matrix

# Explicit matrix coordinate
uv run python scripts/run_cross_agent_benchmark.py \
  --family hotpotqa --agent hermes --backend no_memory --seed 1

# Offline tests (included in default pytest suite)
uv run pytest tests/test_cross_agent_benchmark.py tests/test_cross_agent_agent_runners.py -v
```

## Extending adapters

Register independent implementations without modifying the harness core:

```python
from benchmarks.cross_agent.backends import register_memory_backend
from benchmarks.cross_agent.agents import register_agent_runner
from benchmarks.cross_agent.types import MemoryBackendKind, AgentKind

register_memory_backend(MemoryBackendKind.MEM0, MyMem0Backend)
register_agent_runner(AgentKind.OPENCLAW, MyOpenClawRunner)
```

Adapters must honor the protocols in `benchmarks/cross_agent/protocol.py` and keep
storage confined to the per-run directory passed to `open()`.
