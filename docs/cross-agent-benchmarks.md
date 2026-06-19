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
| `native_memory` | Implemented | Agent-owned memory via optional `AgentNativeMemoryBridge` |
| `openviking` | Implemented | Requires `openviking` package (no silent fallback) |
| `mem0` | Implemented | Requires `mem0ai` package (no silent fallback) |

| Agent | Status in repo | Notes |
|-------|----------------|-------|
| `openclaw` | CLI runner + mock | Production via isolated `OPENCLAW_STATE_DIR`; offline via `use_mock_agent=True` |
| `hermes` | CLI runner + mock | Production via isolated `HERMES_HOME`; offline via `use_mock_agent=True` |
| `claude_code` | CLI runner + mock | Production via isolated `CLAUDE_CONFIG_DIR`; offline via `use_mock_agent=True` |
| `codex` | CLI runner + mock | Production via isolated `CODEX_HOME`; offline via `use_mock_agent=True` |

### Agent runner compatibility matrix

Production CLI runners support `no_memory` and `hm_arch` for all four agents.
Other backend combinations are available with the mock runner (`use_mock_agent=True`)
when the backend matrix permits them. Unsupported cells are reported in
`agent_metadata` and `compatibility` without silent substitution.

See [agents/benchmark-compatibility-matrix.md](agents/benchmark-compatibility-matrix.md)
for the full agent × backend grid.

### Provider/agent compatibility matrix

Unsupported combinations raise `UnsupportedCombinationError`; the harness does
not silently substitute another provider.

| Backend | OpenClaw | Hermes | Claude Code | Codex |
|---------|:--------:|:------:|:-----------:|:-----:|
| `no_memory` | Yes | Yes | Yes | Yes |
| `hm_arch` | Yes | Yes | Yes | Yes |
| `native_memory` | Yes | Yes | Yes | Yes |
| `mem0` | Yes* | Yes* | No | No |
| `openviking` | Yes* | No | No | No |

\* Requires the external package and agent-specific configuration. See
[External service requirements](#external-service-requirements).

Reason strings are available from
`benchmarks.cross_agent.compatibility.compatibility_cell` and
`unsupported_pairs()`.

## Lifecycle phases

1. **setup** — create isolated storage directory, always call `backend.open()`
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
| `recall_context_chars` | Length of recalled context string | Recall step only |
| `recall_hit_count` | Provider-reported hit count from recall | Recall step only |
| `agent_managed` | `true` when native-memory mode delegates to the agent | Recall step only |
| `agent_time_ms` | Wall time inside `agent.answer()` | Agent start → agent return |
| `query_time_ms` | Wall time for recall **and** agent answer for one query | Before recall → after agent return |
| `input_tokens` | CLI-reported usage when available, else whitespace token estimate of prompt passed to agent | Agent step |
| `output_tokens` | CLI-reported usage when available, else whitespace token estimate of agent answer | Agent step |
| `input_token_source` / `output_token_source` | `exact` when parsed from CLI JSON/JSONL usage; `estimated` otherwise | Agent step |
| `failure_count` | Sum of recall and agent failures for the query | Recall + agent steps |

## Result schema

Each run writes under ``<output-dir>/<run_id>/``:

- `queries.jsonl` — one JSON object per query (streamed during the run)
- `queries.csv` — tabular roll-up of all query metrics
- `summary.json` — run config, aggregates, environment metadata
- `storage/` — isolated backend state and `checkpoint.json` (persists across agent workspace teardown)
- `agent_workspace/` — disposable per-run agent home and project workspace (removed after successful CLI runs)

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
sha256("{family}|{agent}|{backend}|{seed}|{top_k}")[:16]
```

prefixed as `{family}-{agent}-{backend}-s{seed}-k{top_k}-<digest>`.

All result-affecting matrix coordinates (`family`, `agent`, `backend`, `seed`,
`top_k`) are included so runs with different retrieval depth never share storage
or checkpoints. The full config is also persisted in `checkpoint.json`.

Fresh runs (`resume=False`) reset the run directory before writing artifacts.
Re-running with the same derived id therefore replaces `queries.jsonl`, CSV, and
summary rather than appending to stale JSONL.

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
uv run pytest tests/test_cross_agent_benchmark.py tests/test_cross_agent_memory_backends.py -v
```

## External service requirements

**Mem0**

- Package: `pip install mem0ai`
- For OSS mode the adapter writes a local Qdrant path under the isolated run
  storage directory (`storage/qdrant`).
- Platform mode requires `MEM0_API_KEY` and is not used by default offline tests.
- Offline contract tests inject `OfflineMem0Client` directly; production runs
  without injection fail fast with `ProviderPackageRequired`.

**OpenViking**

- Package: `pip install openviking`
- Embedded mode stores data under `storage/openviking`.
- HTTP mode can be wired by passing a custom client implementing
  `OpenVikingClientProtocol`.
- Offline contract tests inject `OfflineOpenVikingClient` directly.

**HM-Arch**

- No external services. Uses SQLite under `storage/hm_arch.db`.

**Native memory**

- Supply an `AgentNativeMemoryBridge` to `NativeMemoryBackend(..., bridge=...)`
  when the agent runner owns recall/ingest. Without a bridge the backend reports
  `agent_managed=True` and returns empty context so benchmarks can distinguish
  the mode from `no_memory`.

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
