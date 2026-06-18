# Cross-agent memory benchmarks (HM-65)

Reproducible comparisons of agent memory systems across **OpenClaw**, **Hermes**,
**Claude Code**, and **Codex**. These benchmarks are separate from the offline
[PRD performance suite](benchmarks.md) (`benchmarks/harness.py`), which validates
HM-Arch SDK latency and storage contracts.

Cross-agent benchmarks answer: *given the same conversations or tasks, how do
different memory backends affect accuracy, retrieval quality, query latency, and
token cost?*

## Memory backends

Each benchmark run selects one memory mode. Modes are mutually exclusive and must
be distinguishable in result metadata:

| Backend ID | Description |
|------------|-------------|
| `no-memory` | Agent runs with memory disabled. Baseline for task success and token use. |
| `native-memory` | The agent's built-in memory only (Codex memories, Claude Code native context, Hermes default provider, OpenClaw native slot). |
| `hm-arch` | HM-Arch integration for that agent (hooks, Hermes provider, or OpenClaw plugin + sidecar). |
| `mem0` | Mem0 configured as the active external memory provider. |
| `openviking` | OpenViking configured as the active external memory provider. |

Unsupported agent × backend cells are recorded explicitly in reports as
`unsupported` with a reason string. Failed runs are counted separately from
unsupported cells.

## Agent × backend matrix

For every supported agent, the harness attempts the full backend list above.
Not every cell is expected to succeed on every host (missing CLIs, provider
credentials, or agent-specific integration gaps).

| Agent | `no-memory` | `native-memory` | `hm-arch` | `mem0` | `openviking` |
|-------|:-----------:|:-----------------:|:---------:|:------:|:------------:|
| OpenClaw | ✓ | ✓ | ✓ | ✓ | ✓ |
| Hermes | ✓ | ✓ | ✓ | ✓ | ✓ |
| Claude Code | ✓ | ✓ | ✓ | ✓ | ✓ |
| Codex | ✓ | ✓ | ✓ | ✓ | ✓ |

See [agents/compatibility-matrix.md](agents/compatibility-matrix.md) for
install/status/doctor support per agent.

## Datasets

| Dataset | Primary question | Notes |
|---------|------------------|-------|
| **LoCoMo** | Long-conversation user memory and multi-session recall | Category-level answer accuracy, evidence recall where annotated |
| **tau2-bench** | Multi-turn task completion (retail and airline domains) | Task success/accuracy under memory on vs off |
| **HotpotQA** | Knowledge retrieval and multi-hop QA | Runs at `top_k = 5` and `top_k = 20` |

Dataset adapters live under `benchmarks/cross_agent/datasets/`. Synthetic offline
fixtures exercise the full harness lifecycle without external APIs.

## Metrics

All runs capture a common metric envelope. Timing boundaries start at the memory
query or retrieval call boundary and end when context is returned to the agent
runner (excluding downstream model inference unless noted in the dataset adapter).

| Metric | Definition |
|--------|------------|
| **Accuracy / task success** | Dataset-specific scoring (LoCoMo category accuracy, tau2 success bit, HotpotQA EM/F1 as configured by the adapter) |
| **Retrieval hit rate** | Fraction of questions where ground-truth evidence appears in retrieved context (when annotations exist) |
| **Recall@K** | HotpotQA retrieval metric at configured `top_k` |
| **Average query time** | Mean wall-clock memory query latency per episode |
| **p95 query time** | 95th percentile memory query latency per episode |
| **Input tokens** | Total prompt/input tokens attributed to the run (including injected memory context) |
| **Average input tokens** | Mean input tokens per episode or question |
| **Output tokens** | Total model output tokens when the runner records them |
| **Failures / timeouts** | Count of non-success outcomes (tool errors, harness timeout, agent CLI failure) |
| **Index / ingestion cost** | Wall-clock or token cost to ingest corpus items where the backend exposes it |

HM-Arch sidecar telemetry (when available) also records hit count, returned
character count, and storage latency per query.

## Commands

### Offline harness smoke (synthetic fixtures)

```bash
uv run pytest benchmarks/cross_agent/tests -m cross_agent -v
```

### Full cross-agent suite

```bash
uv run python scripts/run_cross_agent_benchmarks.py --help
uv run python scripts/run_cross_agent_benchmarks.py --dataset locomo --output /tmp/locomo.json
uv run python scripts/run_cross_agent_benchmarks.py --dataset tau2 --output /tmp/tau2.json
uv run python scripts/run_cross_agent_benchmarks.py --dataset hotpotqa --top-k 5 --output /tmp/hotpotqa-k5.json
uv run python scripts/run_cross_agent_benchmarks.py --dataset hotpotqa --top-k 20 --output /tmp/hotpotqa-k20.json
```

### Dataset-specific entry points

```bash
uv run python scripts/run_cross_agent_benchmarks.py --dataset locomo --agents openclaw,hermes,claude-code,codex
uv run python scripts/run_cross_agent_benchmarks.py --dataset tau2 --domains retail,airline
```

Default `uv run pytest` excludes `cross_agent`-marked tests (see `pyproject.toml`).

### Isolation requirements

Benchmark runners must use temporary agent homes (`OPENCLAW_HOME`, `HERMES_HOME`,
isolated Codex/Claude project directories) and per-run SQLite stores. Never
point harness defaults at a developer's live agent configuration.

## Result schema

`scripts/run_cross_agent_benchmarks.py` writes structured JSON. Top-level fields:

```json
{
  "run_id": "20260618T153000Z-abc123",
  "dataset": "locomo",
  "harness_version": "0.1.0",
  "environment": {
    "python": "3.12.3",
    "platform": "linux-x86_64",
    "hm_arch_version": "2.1.0"
  },
  "matrix": [
    {
      "agent": "openclaw",
      "backend": "hm-arch",
      "status": "completed",
      "metrics": {
        "accuracy": null,
        "retrieval_hit_rate": null,
        "avg_query_time_ms": null,
        "p95_query_time_ms": null,
        "input_tokens_total": null,
        "input_tokens_avg": null,
        "output_tokens_total": null,
        "failures": 0,
        "timeouts": 0
      },
      "artifact_path": "results/locomo/openclaw-hm-arch.jsonl"
    }
  ],
  "summary": {
    "completed_cells": 0,
    "unsupported_cells": 0,
    "failed_cells": 0
  }
}
```

Per-episode JSONL rows include `episode_id`, `agent`, `backend`, `question_id`,
scores, timing, token counts, and optional `retrieved_ids` / `ground_truth_ids`
for hit-rate computation.

Published accuracy, latency, or token claims in release notes **must** link to a
committed result artifact under `benchmarks/cross_agent/results/` or a release
attachment. Do not publish headline numbers before artifacts exist.

## Example results

**No published cross-agent benchmark numbers yet.** After benchmark execution
(HM-75, HM-76, HM-77), fill the table below from checked-in artifacts:

| Dataset | Agent | Backend | Accuracy | Avg query (ms) | Input tokens (avg) | Artifact |
|---------|-------|---------|----------|----------------|--------------------|----------|
| LoCoMo | — | — | _pending_ | _pending_ | _pending_ | _pending_ |
| tau2-bench | — | — | _pending_ | _pending_ | _pending_ | _pending_ |
| HotpotQA | — | — | _pending_ | _pending_ | _pending_ | _pending_ |

Re-run the harness on your hardware for authoritative numbers.

## Known limitations

- **Not a full academic study** — no rigorous statistical testing; comparisons
  are engineering benchmarks on fixed harness versions.
- **Agent CLI variance** — different agent versions, model choices, and gateway
  settings change absolute scores; compare runs with pinned agent versions recorded
  in `environment`.
- **External providers** — Mem0 and OpenViking runs may require credentials,
  network access, and provider-specific setup not needed for offline HM-Arch runs.
- **Native memory opacity** — native-memory mode behavior depends on each agent's
  undocumented internal storage; treat as best-effort replay, not bit-identical
  reproduction.
- **Token attribution** — input/output token counts depend on agent telemetry;
  some runners estimate tokens when the agent does not expose usage metadata.
- **HotpotQA ingestion** — index/ingestion cost is reported only when the backend
  adapter exposes measurable ingest timing.
- **Parallel workstreams** — harness code, agent runners, and OpenClaw plugin
  land incrementally; synthetic offline tests may pass before all live agent
  cells are runnable.

## Related docs

- [PRD performance benchmarks](benchmarks.md) — SDK latency, storage, consolidation
- [OpenClaw setup](agents/openclaw.md)
- [Agent compatibility matrix](agents/compatibility-matrix.md)
- [Integration CLI smoke tests](integration-cli-smoke.md)
