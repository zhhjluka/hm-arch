# Cross-agent memory benchmark backends (HM-72 / MEM-73)

Comparable benchmark backends for HM-Arch, Mem0, OpenViking, agent-native
memory, and a no-memory control. These adapters are intentionally decoupled
from any single agent runner; HM-71 wires them into OpenClaw, Hermes, Claude
Code, and Codex runners.

## Providers

| Provider ID | Purpose | Offline contract tests |
|-------------|---------|------------------------|
| `no-memory` | Control arm with zero external recall | Always offline |
| `hm-arch` | HM-Arch via `execute_recall` / `execute_record` / `execute_consolidate` | Always offline |
| `mem0` | Mem0 OSS or platform client | Offline fallback client when `mem0ai` is not installed |
| `openviking` | OpenViking embedded or HTTP client | Offline fallback client when `openviking` is not installed |
| `native-memory` | Agent-owned memory via optional bridge | Offline; bridge optional |

## Normalized lifecycle

Every backend implements the same contract:

1. `setup()` — create an isolated namespace under `workspace_root/run_id/namespace/provider_id`
2. `ingest(turn)` — persist a normalized `IngestTurn`
3. `recall(query)` — return context plus `ProviderOperationMetrics`
4. `consolidate()` — optional provider-side consolidation
5. `reset()` — clear provider state and recreate the namespace
6. `teardown()` — release resources and delete isolated storage

`ProviderOperationMetrics` records provider-side latency in milliseconds and the
returned context size (`context_chars`, `hit_count`, `ingested_count`).

## Provider/agent compatibility matrix

Unsupported combinations raise `UnsupportedCombinationError`; the harness must
not silently substitute another provider.

| Provider | OpenClaw | Hermes | Claude Code | Codex |
|----------|:--------:|:------:|:-----------:|:-----:|
| `no-memory` | Yes | Yes | Yes | Yes |
| `hm-arch` | Yes | Yes | Yes | Yes |
| `native-memory` | Yes | Yes | Yes | Yes |
| `mem0` | Yes* | Yes* | No | No |
| `openviking` | Yes* | No | No | No |

\* Requires the external package and agent-specific configuration.

Reason strings are available from `benchmarks.agent_memory.compatibility.compatibility_cell`
and `unsupported_pairs()`.

## Configuration

```python
from pathlib import Path

from benchmarks.agent_memory import (
    AgentId,
    MemoryBackendRunConfig,
    MemoryProviderId,
    create_memory_backend,
)

config = MemoryBackendRunConfig(
    run_id="locomo-001",
    namespace="session-a",
    workspace_root=Path("/tmp/hm-arch-benchmarks"),
    agent_id=AgentId.CODEX,
    provider_id=MemoryProviderId.HM_ARCH,
    recall_top_k=5,
    max_context_chars=8000,
)

backend = create_memory_backend(config)
backend.setup()
try:
    backend.ingest(
        IngestTurn(
            user_message="User prefers pytest fixtures.",
            agent_message="Noted.",
        )
    )
    result = backend.recall("pytest preferences")
    print(result.metrics.latency_ms, result.metrics.context_chars)
finally:
    backend.teardown()
```

### External service requirements

**Mem0**

- Optional package: `pip install mem0ai`
- For OSS mode the adapter writes a local Qdrant path under the isolated
  namespace (`storage_dir/qdrant`).
- Platform mode requires `MEM0_API_KEY` and is not used by default offline tests.

**OpenViking**

- Optional package: `pip install openviking`
- Embedded mode stores data under `storage_dir/openviking`.
- HTTP mode can be wired by passing a custom client implementing
  `OpenVikingClientProtocol`.

**HM-Arch**

- No external services. Uses SQLite under `storage_dir/benchmark.db` via the
  public integration runtime handlers.

**Native memory**

- Supply an `AgentNativeMemoryBridge` to `NativeMemoryBackend(..., bridge=...)`
  when the agent runner owns recall/ingest. Without a bridge the backend reports
  `agent_managed=True` and returns empty context so benchmarks can distinguish
  the mode from `no-memory`.

## Tests

```bash
uv run pytest tests/test_agent_memory_backends.py -v
```

Contract tests run fully offline using in-process Mem0 and OpenViking fallback
clients. Default `uv run pytest` includes these tests.

## Related issues

- HM-71 / MEM-68: common harness, datasets, and agent runners
- HM-65 / MEM-65: parent cross-agent benchmark program
