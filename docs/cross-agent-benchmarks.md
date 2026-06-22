# Cross-agent memory benchmarks (HM-71 / MEM-68)

Reproducible harness for **LoCoMo**, **tau2-bench**, and **HotpotQA** across host
agents and memory providers. The PRD-scale HM-Arch benchmarks live in
[benchmarks.md](benchmarks.md); this document covers the cross-agent matrix,
provider contracts, and result schema.

Do not publish headline benchmark numbers unless a corresponding committed result
artifact exists in the repository.

## Goals

- One shared lifecycle for ingest → consolidate → query → evaluate
- Pluggable :class:`~benchmarks.cross_agent.protocol.MemoryBackend` and
  :class:`~benchmarks.cross_agent.protocol.AgentRunner` adapters
- Deterministic run identifiers and isolated per-run storage
- JSONL per-query streaming, CSV roll-up, and JSON summary output
- Checkpoint/resume between lifecycle phases and individual queries
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
| `mock-only` | In-process offline substitute (for example `OfflineMem0Client`, `MockSyntheticAgentRunner`). Contract tests only. | **No** — label results `mock-only`; never compare to `real` runs. |
| `unavailable` | Supported in the matrix but not runnable on this host (missing package, credentials, agent CLI absent). | No — record reason; do not substitute another provider. |
| `unsupported` | Provider × agent pair excluded by the compatibility matrix. | No — harness skips or records `unsupported` with reason. |

Rules:

- Mock/fallback clients exercise contracts offline but **must not** be labeled
  `real` or merged into production comparison tables.
- `assert_supported()` / compatibility checks **must not** silently substitute
  another provider when a cell is `unsupported`.
- Mem0 and OpenViking adapters may use offline fallbacks when the external
  package is missing; those runs are `mock-only`, not `real`.

## Registered providers

| Memory backend | Status in repo | Notes |
|----------------|----------------|-------|
| `no_memory` | Implemented | Empty-recall baseline |
| `hm_arch` | Implemented | SQLite-isolated HM-Arch adapter |
| `native_memory` | Unsupported | Requires agent-specific `AgentNativeMemoryBridge`; no production bridge wired |
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
for the full agent × backend grid with `real` / `unsupported` labels.

### Provider/agent compatibility matrix

Unsupported combinations raise `UnsupportedCombinationError`; the harness does
not silently substitute another provider.

| Backend | OpenClaw | Hermes | Claude Code | Codex |
|---------|:--------:|:------:|:-----------:|:-----:|
| `no_memory` | Yes | Yes | Yes | Yes |
| `hm_arch` | Yes | Yes | Yes | Yes |
| `native_memory` | No | No | No | No |
| `mem0` | Yes* | Yes* | No | No |
| `openviking` | Yes* | No | No | No |

\* Requires the external package and agent-specific configuration. See
[External service requirements](#external-service-requirements).

Reason strings are available from
`benchmarks.cross_agent.compatibility.compatibility_cell` and
`unsupported_pairs()`.

## Datasets

| Dataset | Primary question | Notes |
|---------|------------------|-------|
| **LoCoMo** | Long-conversation user memory and multi-session recall | Pilot uses normalized exact match; not official LoCoMo category-aware token F1 |
| **tau2-bench** | Multi-turn task completion (retail and airline domains) | Task success/accuracy under memory on vs off |
| **HotpotQA** | Knowledge retrieval and multi-hop QA | Runs at `top_k = 5` and `top_k = 20` |

Synthetic fixtures in `benchmarks/cross_agent/fixtures/synthetic.py` exercise every
phase offline without API keys.

## Lifecycle phases

1. **setup** — create isolated storage directory, always call `backend.open()`
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
| `retrieval_hit_rate` | Fraction of `expected_memory_ids` present in `retrieved_ids`; `null` when fixture provides none or when HM-Arch hooks own recall | Recall step only (skipped when hook-managed) |
| `recall_time_ms` | Wall time inside `backend.recall()` | Recall start → recall return |
| `recall_context_chars` | Length of recalled context string | Recall step only |
| `recall_hit_count` | Provider-reported hit count from recall | Recall step only |
| `agent_managed` | `true` when native-memory mode delegates to the agent | Recall step only |
| `agent_time_ms` | Wall time inside `agent.answer()` | Agent start → agent return |
| `query_time_ms` | Wall time for recall **and** agent answer for one query; equals `agent_time_ms` when HM-Arch hooks own recall | Before recall → after agent return (recall skipped when hook-managed) |
| `input_tokens` | CLI-reported usage when available, else whitespace token estimate of prompt passed to agent | Agent step |
| `output_tokens` | CLI-reported usage when available, else whitespace token estimate of agent answer | Agent step |
| `input_token_source` / `output_token_source` | `exact` when parsed from CLI JSON/JSONL usage; `estimated` otherwise | Agent step |
| `failure_count` | Sum of recall and agent failures for the query | Recall + agent steps |

### LoCoMo pilot accuracy (MEM-78)

The committed LoCoMo real-CLI pilot (`benchmarks/cross_agent/fixtures/locomo/handoff/`)
uses **normalized exact match** after whitespace normalization. This pilot metric is
**not** the official LoCoMo category-aware token F1 reported in the academic benchmark.
Do not compare pilot `mean_accuracy` values directly to published LoCoMo leaderboard
scores.

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

Matrix roll-ups add per-cell status:

| Cell status | Meaning |
|-------------|---------|
| `completed` | Run finished with recorded metrics |
| `partial` | Run produced some query results but did not complete the requested workload |
| `unsupported` | Matrix excludes this provider × agent pair |
| `unavailable` | Supported but could not run on this host |
| `failed` | Run started but ended with errors/timeouts |

The per-query schema supports all three families:

- **LoCoMo** — conversational ingest + multi-session QA with `expected_memory_ids`
- **tau2-bench** — task logs with `task_success_criteria`
- **HotpotQA** — multi-document ingest + multi-hop QA with `supporting_facts`

## Deterministic run identifiers

When `run_id` is omitted, the harness derives:

```
sha256("{family}|{agent}|{backend}|{seed}|{top_k}|{dataset_id}|{dataset_version}|{max_conversations}|{max_queries}")[:16]
```

prefixed as `{family}-{agent}-{backend}-s{seed}-k{top_k}-<digest>`.

All result-affecting matrix coordinates are included so runs with different
datasets or workload limits never share storage or checkpoints. Optional fields
are encoded as empty strings when unset. The full config is also persisted in
`checkpoint.json`.

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

# LoCoMo cross-agent memory matrix (MEM-78)
uv run python scripts/run_locomo_matrix.py --dataset-id locomo10-sample

# Real supported agent CLI comparison (Hermes/Claude/Codex no_memory + hm_arch)
uv run python scripts/run_locomo_matrix.py \
  --runner-mode real --dataset-id locomo10-sample --max-conversations 1

# tau2-bench agent experience comparison
uv run python scripts/run_tau2_bench_comparison.py

# HotpotQA retrieval matrix
uv run python scripts/run_hotpotqa_matrix.py

# Offline tests (included in the default pytest suite)
uv run pytest tests/test_cross_agent_benchmark.py tests/test_cross_agent_memory_backends.py -v
uv run pytest tests/test_locomo_matrix.py -v
```

### LoCoMo matrix reporting (MEM-78)

`scripts/run_locomo_matrix.py` orchestrates the 4×5 agent × backend grid with
versioned LoCoMo ingestion. Two runner modes are reported separately:

| Mode | Flag | Output | Purpose |
|------|------|--------|---------|
| `mock` | default | `matrix_summary_mock.json` | Offline smoke only — **not** cross-agent CLI comparison |
| `real` | `--runner-mode real` | `matrix_summary_real.json` | Production CLI runs for supported cells |

`matrix_summary.json` is a pointer to the active report file. Each completed
cell links to per-run `summary.json`, `queries.jsonl`, and `invocations.jsonl`.
Invocation arguments, stdout, and stderr are captured with recursive secret
redaction. Real-mode summaries include CLI/provider version provenance and the
exact reproducible shell command.

**Handoff artifacts** (committed real-CLI pilot results) live under
`benchmarks/cross_agent/fixtures/locomo/handoff/`. Regenerate with:

```bash
scripts/run_locomo_matrix_handoff.sh
```

Use `--max-queries N` for pilot runs. Per-agent CLI overrides:
`--codex-executable`, `--claude-code-executable`, `--hermes-executable`,
`--openclaw-executable`, or `HM_ARCH_BENCH_*_EXECUTABLE` env vars.

OpenClaw cells are included with `--include-openclaw`. When the OpenClaw CLI is
absent, cells are recorded as `unavailable` without aborting the matrix.
Unsupported cells are listed with explicit rationale and are never silently
substituted.

### Isolation requirements

Benchmark runners must use temporary agent homes (`OPENCLAW_STATE_DIR`, `HERMES_HOME`,
isolated Codex/Claude project directories) and per-run SQLite stores. Never
point harness defaults at a developer's live agent configuration.

## Committed pilot artifacts

The repository contains committed cross-agent benchmark pilots:

| Dataset | Git-tracked artifact | Pilot status |
|---------|---------------------|--------------|
| LoCoMo | `benchmarks/cross_agent/fixtures/locomo/handoff/` | Real-CLI handoff (1 conversation, 3 queries/cell) |
| HotpotQA | `benchmark-results/hotpotqa/matrix_summary.json` | **Incomplete pilot** — 4 completed / 4 failed / 8 pending / 24 unsupported (`status=run` encodes outcomes) |
| tau2-bench | `benchmark-results/tau2-comparison/` | **Availability record** — `tau2_importable=false`; all matrix cells `unavailable`/`unsupported` |

Do not cite HotpotQA or tau2 headline comparison numbers from these artifacts until
cells reach `completed` with `runner_mode=real` and `use_mock_agent=false`. The
HotpotQA committed summary records partial Claude Code/Codex runs only; OpenClaw and
Hermes cells remain `pending` when their CLIs are absent.

The LoCoMo handoff scope and limitations are documented in
[benchmarks/cross_agent/fixtures/locomo/handoff/README.md](../benchmarks/cross_agent/fixtures/locomo/handoff/README.md).

| Property | LoCoMo pilot value |
|----------|-------------------|
| Dataset | `locomo10-sample` / `2024-03-sample` |
| Conversations | 1 |
| Queries per completed cell | 3 |
| Agents | OpenClaw, Hermes, Claude Code, Codex (`no_memory` + `hm_arch`) |
| Accuracy metric | Normalized exact match (not official LoCoMo token F1) |
| Artifact | `benchmarks/cross_agent/fixtures/locomo/handoff/matrix_summary_real.json` |

Read per-cell `status`, `runner_mode`, and `mean_accuracy` from each artifact;
the top-level `test_double_mode` flag identifies offline test-double output.
Failed, unavailable, partial, and pending cells are first-class outcomes and are
excluded from completed-query aggregates. Do not quote headline comparison numbers
outside the artifact context.

### HotpotQA committed pilot (`benchmark-results/hotpotqa/`)

Git-tracked matrix summary and per-run summaries under `benchmark-results/hotpotqa/`.
Regenerate with:

```bash
python scripts/run_hotpotqa_matrix.py --use-real-cli
```

Pilot limitations:

- `matrix_size` is 40 cells; the committed artifact records **4 completed**, **4 failed**,
  **8 pending**, and **24 unsupported** cells (top-level counters match per-cell rows).
- Executed cells use `status=run`. Derive outcomes from query counters:
  - **completed run** — `completed_query_count > 0` and `total_failure_count == 0`
  - **failed run** — `total_failure_count > 0` and `completed_query_count == 0`
- `pending` and `unsupported` cells were never executed on the host that produced
  the artifact. Do not treat their metrics as headline comparisons.
- Top-level `tradeoffs` strings are host-specific notes, not release headline claims.

### tau2-bench committed pilot (`benchmark-results/tau2-comparison/`)

Git-tracked availability record: `matrix_status.json`, `summary_table.json`,
`provenance.json`, and roll-up tables. Regenerate with:

```bash
python scripts/run_tau2_bench_comparison.py
```

Pilot limitations:

- `provenance.json` records `tau2_importable` and agent CLI availability for the
  host that produced the artifact.
- When `tau2_importable` is false or agent CLIs are absent, treat the directory as
  an availability record, not benchmark results suitable for a headline.
- `summary_table.json` rows may set `excluded_from_benchmark_table=true` for
  scripted-user pilot runs that are not benchmark-eligible.

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

- All agent × `native_memory` cells are **unsupported** until an agent-specific
  bridge can drive the shared ingest lifecycle.
- Supply an `AgentNativeMemoryBridge` to `NativeMemoryBackend(..., bridge=...)`
  in custom integrations; the harness does not run production cells without one.

## CLI capability detection

Production CLI runners probe executable capabilities once during `open()` and
cache the resolved mode (`real` vs `hm-arch-benchmark` test double). Unsupported
executables raise `NotImplementedError` at setup time instead of failing every
query. Malformed JSON from Claude Code or OpenClaw `--json` output is counted as
an agent failure, not accepted as raw text.

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
- **LoCoMo pilot metric** — committed pilot accuracy is normalized exact match,
  not official LoCoMo category-aware token F1.
- **Token attribution** — input/output token counts depend on agent telemetry;
  some runners estimate tokens when the agent does not expose usage metadata.

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

## Related docs

- [PRD performance benchmarks](benchmarks.md) — SDK latency, storage, consolidation
- [OpenClaw setup](agents/openclaw.md)
- [Agent compatibility matrix](agents/compatibility-matrix.md)
- [Benchmark compatibility matrix](agents/benchmark-compatibility-matrix.md)
- [Integration CLI smoke tests](integration-cli-smoke.md)
