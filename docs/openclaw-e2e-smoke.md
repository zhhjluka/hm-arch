# OpenClaw end-to-end smoke test

Manual verification for a **real** OpenClaw installation with the canonical
`@hm-arch/openclaw-plugin`, Python sidecar, and `hm-arch` / `@hm-arch/installer`
management CLI.

Automated coverage lives in:

- `tests/test_integrations_openclaw_e2e.py` (Python orchestration)
- `packages/openclaw-plugin/test/e2e.test.ts` (plugin + live sidecar)
- `scripts/run_openclaw_e2e.py` (artifact capture)

**Do not run these steps against your daily `~/.openclaw` home.** Use an isolated
state directory.

## Versions under test

Record the exact versions in your handoff notes:

```bash
python -c "import hm_arch; print(hm_arch.__version__)"
node -e "console.log(require('./packages/openclaw-plugin/package.json').version)"
openclaw --version  # when OpenClaw CLI is installed
```

Current HM-Arch release line: **2.0.4** (`hm-arch`, `@hm-arch/openclaw-plugin`,
`@hm-arch/installer`).

## 1. Isolated OpenClaw home

```bash
export OPENCLAW_E2E_HOME="$(mktemp -d)"
export HOME="$OPENCLAW_E2E_HOME"
export OPENCLAW_STATE_DIR="$OPENCLAW_E2E_HOME/.openclaw"
mkdir -p "$OPENCLAW_E2E_HOME/project"
cd "$OPENCLAW_E2E_HOME/project"
```

Optional project-local config instead of global state:

```bash
export OPENCLAW_CONFIG_PATH="$OPENCLAW_E2E_HOME/project/.openclaw/openclaw.json"
```

## 2. Install HM-Arch OpenClaw integration

**Python package path:**

```bash
python -m pip install -e "/path/to/hm-arch[dev]"
hm-arch install openclaw
hm-arch status openclaw
hm-arch doctor openclaw
```

**npm installer path (Python on PATH or standalone runtime):**

```bash
npx @hm-arch/installer install openclaw
npx @hm-arch/installer status openclaw
npx @hm-arch/installer doctor openclaw
```

Expected:

- `plugins.slots.memory` is `memory-hm-arch`
- Extension files exist under `.openclaw/extensions/memory-hm-arch/`
- `hm_arch_memory.db` (or configured `dbPath`) is created

## 3. Restart OpenClaw gateway

If the OpenClaw gateway is already running, restart it so the memory plugin loads:

```bash
openclaw gateway restart
```

When OpenClaw is not installed locally, validate install artifacts with the
automated suite instead (`python scripts/run_openclaw_e2e.py`).

## 4. Store → restart → recall

1. Store a distinctive fact with the agent tool or sidecar:

   - Tool: `memory_store` with text like `OpenClaw E2E smoke marker 2026-06-20`
   - Or CLI sidecar: `hm-arch openclaw sidecar` + `remember` JSONL request

2. Restart the gateway (or sidecar process).

3. Recall with `memory_recall` or start a new agent turn and confirm auto-recall
   prepends untrusted historical context.

## 5. Hook behavior checklist

| Scenario | Expected |
|----------|----------|
| Auto-recall before prompt build | Untrusted context block prepended; failures are non-fatal |
| Auto-capture after agent completion | Exactly one `record_turn` per completed turn |
| Session-end consolidation | `consolidate` runs on idle/shutdown/restart when enabled |
| `memory_recall` / `memory_store` / `memory_forget` | Tools registered and fail open on sidecar errors |
| Sidecar crash/restart | Plugin restarts sidecar; subsequent reads succeed |
| Bounded timeout | Hung sidecar requests time out without wedging later writes |
| Memory slot conflict | `status`/`doctor`/`install` report conflict when another slot is active |

## 6. Shared HM-Arch store with another agent

Point Codex or Claude Code hooks at the same SQLite database path configured in
`plugins.entries.memory-hm-arch.config.dbPath`, store a fact from that agent, then
recall it through OpenClaw. The automated Python E2E covers this with a direct
`HMArch.add(..., agent="codex")` + sidecar `search` round trip.

## 7. Upgrade and uninstall

```bash
hm-arch-install upgrade openclaw   # or: hm-arch upgrade openclaw when available
hm-arch-install uninstall openclaw
```

Expected:

- Plugin extension directory removed
- HM-Arch config entries removed
- SQLite database preserved unless deleted manually

## 8. Run automated E2E suite

From the repository root:

```bash
python -m pip install -e ".[dev]"
python scripts/run_openclaw_e2e.py
```

Artifacts are written to `artifacts/openclaw-e2e/`:

- `run.log` — combined stdout/stderr
- `handoff.json` — versions and platform metadata
- `results.json` — per-step exit codes

Focused pytest only:

```bash
pytest tests/test_integrations_openclaw_e2e.py tests/test_integrations_openclaw_manage.py \
  tests/test_integrations_openclaw_sidecar.py tests/test_integrations_openclaw_wheel.py -q
```

Plugin + live sidecar (requires Node 18+ and installed `hm-arch`):

```bash
cd packages/openclaw-plugin && npm ci && npm test
```

## Platform limitations

| Area | Limitation |
|------|------------|
| Real OpenClaw gateway | Requires locally installed OpenClaw CLI; not run in default CI |
| Node E2E | Skipped when `hm_arch` is not importable from the chosen Python |
| npm installer E2E | Skipped when `npm` is unavailable or build fails |
| Standalone/no-Python npm path | Covered by `packages/installer/test/clean-machine-standalone.test.ts` (needs standalone fixture binary) |
| Windows | Path and shell differences; CI runs npm installer on `windows-latest` |

## Telemetry for benchmarks

Search responses must include `telemetry.query_latency_ms`, `telemetry.hit_count`,
`telemetry.returned_characters`, and `telemetry.returned_tokens`. Remember
responses include `telemetry.storage_latency_ms`. The benchmark harness reads
these fields from sidecar JSONL responses.
