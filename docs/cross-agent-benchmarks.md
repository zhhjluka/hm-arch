# Cross-agent memory benchmarks (HM-71 / MEM-68)

Reproducible harness for **LoCoMo**, **tau2-bench**, and **HotpotQA** across host
agents and memory providers. The PRD-scale HM-Arch benchmarks live in
[benchmarks.md](benchmarks.md); this document covers the cross-agent matrix,
provider contracts, and result schema.

> **Implementation status:** The harness (`benchmarks/cross_agent/`,
> `scripts/run_cross_agent_benchmark.py`) and memory-backend adapters
> (`benchmarks/agent_memory/`) land in HM-71/MEM-68 and MEM-73. Methodology and
> schema below are authoritative; run commands apply after those branches merge.
> Do not publish headline numbers until checked-in result artifacts exist.

## Goals

- One shared lifecycle for ingest → consolidate → query → evaluate
- Pluggable memory backends and agent runners with isolated per-run storage
- Deterministic run identifiers and JSONL/CSV/JSON output
- Explicit provider implementation modes so mock/fallback runs are never reported
  as real external providers

## Memory backends

Each benchmark run selects one memory mode. Modes are mutually exclusive and must
be distinguishable in result metadata:

| Backend ID | Description |
|------------|-------------|
| `no_memory` | Agent runs with memory disabled. Baseline for task success and token use. |
| `hm_arch` | HM-Arch integration for that agent (hooks, Hermes provider, or OpenClaw plugin + sidecar). |
| `native_memory` | The agent's built-in memory only. |
| `mem0` | Mem0 configured as the active external memory provider. |
| `openviking` | OpenViking configured as the active external memory provider. |

Human-readable aliases (`no-memory`, `hm-arch`, `native-memory`) map to the enum
values above in CLI flags and JSON output.

## Provider implementation modes

Every matrix cell records **how** the provider was executed. These four values are
distinct and must appear in `summary.json` / matrix roll-ups:

| Mode | Meaning | Reportable as production benchmark? |
|------|---------|--------------------------------------|
| `real` | Live provider or agent integration (installed SDK, configured plugin, agent CLI on PATH). | Yes, when the run completes successfully. |
| `mock-only` | In-process offline substitute (for example `OfflineMem0Client`, synthetic agent runner). Contract tests only. | **No** — label results `mock-only`; never compare to `real` runs. |
| `unavailable` | Supported in the matrix but not runnable on this host (missing package, credentials, runtime stub, agent CLI absent). | No — record reason; do not substitute another provider. |
| `unsupported` | Provider × agent pair excluded by the compatibility matrix. | No — harness skips or records `unsupported` with reason. |

Rules (MEM-68 / MEM-71 / MEM-73):

- Mock/fallback clients exercise contracts offline but **must not** be labeled
  `real` or merged into production comparison tables.
- `assert_supported()` / compatibility checks **must not** silently substitute
  another provider when a cell is `unsupported`.
- Mem0 and OpenViking adapters may use offline fallbacks when the external
  package is missing; those runs are `mock-only`, not `real`.

## Agent × backend matrix

| Agent | `no_memory` | `native_memory` | `hm_arch` | `mem0` | `openviking` |
|-------|:-----------:|:---------------:|:---------:|:------:|:------------:|
| OpenClaw | ✓ | ✓ | ✓ | ✓* | ✓* |
| Hermes | ✓ | ✓ | ✓ | ✓* | unsupported |
| Claude Code | ✓ | ✓ | ✓ | unsupported | unsupported |
| Codex | ✓ | ✓ | ✓ | unsupported | unsupported |

\* Requires external package and agent-specific configuration; otherwise
`unavailable` or `mock-only` (offline contract tests).

Unsupported cells (for example Mem0 × Codex) raise `UnsupportedCombinationError`
with a reason string from `benchmarks/agent_memory/compatibility.py`.

See [agents/compatibility-matrix.md](agents/compatibility-matrix.md) for
install/status/doctor support per agent.

## Datasets

| Dataset | Primary question | Notes |
|---------|------------------|-------|
| **LoCoMo** | Long-conversation user memory and multi-session recall | Category-level answer accuracy, evidence recall where annotated |
| **tau2-bench** | Multi-turn task completion (retail and airline domains) | Task success/accuracy under memory on vs off |
| **HotpotQA** | Knowledge retrieval and multi-hop QA | Runs at `top_k = 5` and `top_k = 20` |

Synthetic offline fixtures exercise the full harness lifecycle without external
APIs.

## Lifecycle phases

1. **setup** — create isolated storage directory, `backend.open()`
2. **ingest** — persist fixture corpus via `backend.ingest()`
3. **consolidate** — optional `backend.consolidate()` (family-dependent)
4. **query** — for each query: recall → agent answer → per-query metrics
5. **evaluate** — aggregate roll-up metrics (no external scorer required offline)
6. **checkpoint** — persist `checkpoint.json`, JSONL, CSV, and summary JSON
7. **teardown** — `backend.close()`

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

Each run writes under `<output-dir>/<run_id>/`:

- `queries.jsonl` — one JSON object per query (streamed during the run)
- `queries.csv` — tabular roll-up of all query metrics
- `summary.json` — run config, aggregates, environment metadata, `implementation_mode`
- `storage/` — isolated backend state and `checkpoint.json`

`summary.json` top-level fields:

```json
{
  "run_id": "locomo-codex-hm_arch-s0-a1b2c3d4",
  "config": {
    "family": "locomo",
    "agent": "codex",
    "backend": "hm_arch",
    "seed": 0,
    "top_k": 5
  },
  "implementation_mode": "real",
  "storage_dir": "/tmp/hm-arch-benchmarks/locomo-codex-hm_arch-s0-a1b2c3d4/storage",
  "phases_completed": ["setup", "ingest", "consolidate", "query", "evaluate", "checkpoint", "teardown"],
  "aggregates": {
    "query_count": 0,
    "completed_query_count": 0,
    "mean_accuracy": null,
    "task_success_rate": null,
    "mean_retrieval_hit_rate": null,
    "mean_query_time_ms": 0.0,
    "total_input_tokens": 0,
    "total_output_tokens": 0,
    "total_failure_count": 0
  },
  "environment": {
    "python": "3.12.3",
    "hm_arch_version": "2.0.4"
  }
}
```

Matrix roll-ups add per-cell status:

| Cell status | Meaning |
|-------------|---------|
| `completed` | Run finished with recorded metrics (`implementation_mode` is `real` or `mock-only`) |
| `unsupported` | Matrix excludes this provider × agent pair |
| `unavailable` | Supported but could not run on this host |
| `failed` | Run started but ended with errors/timeouts |

Published accuracy, latency, or token claims in release notes **must** link to a
committed result artifact. Do not publish headline numbers before artifacts exist.

## Deterministic run identifiers

When `run_id` is omitted, the harness derives:

```
sha256("{family}|{agent}|{backend}|{seed}")[:16]
```

prefixed as `{family}-{agent}-{backend}-s{seed}-<digest>`.

## Commands

### After HM-71 merges (harness on `main`)

```bash
# Single synthetic run (default: LoCoMo + Codex + HM-Arch)
uv run python scripts/run_cross_agent_benchmark.py

# All three families
uv run python scripts/run_cross_agent_benchmark.py --matrix

# Explicit matrix coordinate
uv run python scripts/run_cross_agent_benchmark.py \
  --family hotpotqa --agent hermes --backend no_memory --seed 1

# Offline harness tests
uv run pytest tests/test_cross_agent_benchmark.py -v
```

### Memory-backend contract tests (MEM-73)

```bash
uv run pytest tests/test_agent_memory_backends.py -v
```

### Isolation requirements

Benchmark runners must use temporary agent homes (`OPENCLAW_HOME`, `HERMES_HOME`,
isolated Codex/Claude project directories) and per-run SQLite stores. Never
point harness defaults at a developer's live agent configuration.

## Example results

**No published cross-agent benchmark numbers yet.** After benchmark execution,
fill the table below from checked-in artifacts:

| Dataset | Agent | Backend | Mode | Accuracy | Avg query (ms) | Input tokens (avg) | Artifact |
|---------|-------|---------|------|----------|----------------|--------------------|----------|
| LoCoMo | — | — | — | _pending_ | _pending_ | _pending_ | _pending_ |
| tau2-bench | — | — | — | _pending_ | _pending_ | _pending_ | _pending_ |
| HotpotQA | — | — | — | _pending_ | _pending_ | _pending_ | _pending_ |

Re-run the harness on your hardware for authoritative numbers.

## Known limitations

- **Not a full academic study** — no rigorous statistical testing; comparisons
  are engineering benchmarks on fixed harness versions.
- **Agent CLI variance** — different agent versions, model choices, and gateway
  settings change absolute scores; compare runs with pinned agent versions recorded
  in `environment`.
- **External providers** — Mem0 and OpenViking `real` runs require credentials,
  network access, and provider-specific setup not needed for offline HM-Arch runs.
- **Mock-only runs** — offline fallbacks validate contracts but must not be
  reported as external-provider performance.
- **Native memory opacity** — `native_memory` behavior depends on each agent's
  internal storage; treat as best-effort replay, not bit-identical reproduction.
- **OpenClaw runtime stub** — `hm-arch install openclaw` may report `partial`
  until the loadable plugin runtime ships; OpenClaw × `hm_arch` cells are
  `unavailable` for live benchmarks until then.
- **Token attribution** — input/output token counts depend on agent telemetry;
  some runners estimate tokens when the agent does not expose usage metadata.

## Related docs

- [PRD performance benchmarks](benchmarks.md) — SDK latency, storage, consolidation
- [OpenClaw setup](agents/openclaw.md)
- [Agent compatibility matrix](agents/compatibility-matrix.md)
- [Integration CLI smoke tests](integration-cli-smoke.md)
