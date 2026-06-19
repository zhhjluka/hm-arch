# Cross-agent benchmark compatibility matrix (HM-73 / MEM-71)

Production benchmark runners invoke each host agent through its real CLI boundary.
Deterministic mock runners (`mock-synthetic`) are reserved for offline harness tests only.

## Agent × memory backend matrix

| Agent | `no_memory` | `native_memory` | `hm_arch` | `mem0` | `openviking` |
|-------|-------------|-------------------|-----------|--------|--------------|
| **Codex** | real | unsupported | real | unsupported | unsupported |
| **Claude Code** | real | unsupported | real | unsupported | unsupported |
| **Hermes** | real | unsupported | real | unsupported | unsupported |
| **OpenClaw** | real | unsupported | real | unsupported | unsupported |

### Cell labels

| Label | Meaning |
|-------|---------|
| `real` | Production runner invokes the agent CLI/plugin boundary with isolated home, timeout, and stdout/stderr/exit capture |
| `unsupported` | Cell remains visible in reports with an explicit rationale; harness skips execution |
| `mock_only` | Offline deterministic test double (`MockSyntheticAgentRunner`); not used for cross-agent comparison |

Native-memory cells are **unsupported** until each agent's actual native store can be driven by the shared ingest lifecycle without a generic in-process substitute.

## Production runner behavior

Each real runner:

1. Creates an isolated temporary home (`CODEX_HOME`, `CLAUDE_CONFIG_DIR`, `HERMES_HOME`, `OPENCLAW_STATE_DIR`)
2. Installs HM-Arch hooks/providers when the backend is `hm_arch`
3. Invokes the agent executable with a benchmark prompt payload
4. Captures wall-clock time, stdout, stderr, exit status, and token usage (`exact` when CLI JSON exposes usage, else `estimated`)
5. Records `runner_mode=real`, `backend=<backend>`, and `input_token_source` / `output_token_source` in result metadata

Agent CLIs use real one-shot boundaries when available:

| Agent | Production invocation |
|-------|----------------------|
| Codex | `codex exec --json --disable memories <prompt>` |
| Claude Code | `claude -p <prompt> --output-format json` |
| Hermes | `hermes -z <prompt>` |
| OpenClaw | `openclaw agent --agent main --local --json --message <prompt>` |

Offline smoke tests may override executables with `tests/fixtures/fake_agent_cli.py`, which implements the same CLI shapes plus the legacy `hm-arch-benchmark answer` test double.

Override the executable in tests or CI with:

```bash
export HM_ARCH_BENCH_CODEX_EXECUTABLE=/path/to/fake-codex
# or pass BenchmarkRunConfig(agent_executable=...)
```

## Smoke dataset

Shared smoke fixture: `cross-agent-smoke-v1` in `benchmarks/cross_agent/fixtures/smoke.py`.

Offline smoke tests use `tests/fixtures/fake_agent_cli.py` as a deterministic CLI double implementing the real one-shot CLI shapes (Codex JSONL, Claude JSON, Hermes `-z`, OpenClaw `agent --json`) and the legacy `hm-arch-benchmark answer` contract.

## Related docs

- [Cross-agent benchmarks](../cross-agent-benchmarks.md)
- [Agent installation guides](README.md)
