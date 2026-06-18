# OpenClaw setup (HM-Arch)

Install HM-Arch as OpenClaw's native memory provider. OpenClaw integration uses
a TypeScript memory plugin backed by a persistent Python sidecar that exposes
HM-Arch recall, capture, forget, and consolidation without per-query process
startup.

All management commands are offline and do not require LLM/API keys.

## Current availability

| Path | Status | Notes |
|------|--------|-------|
| `hm-arch install openclaw` | **Available** (main) | Registers config, plugin manifest, and SQLite database. Reports `partial` until the loadable runtime package ships. |
| `hm-arch status openclaw` / `doctor openclaw` | **Available** (main) | Inspect slot, sidecar command, storage, and runtime stub warnings. |
| `hm-arch uninstall openclaw` | **Available** (main) | Removes HM-Arch-owned config and plugin files; preserves the database. |
| `npx @hm-arch/installer install openclaw` | **Pending** (MEM-74) | Not advertised in the published `@hm-arch/installer` release yet. Use the Python CLI until the next coordinated npm release. |

`hm-arch install openclaw` is registered in the CLI (`codex`, `claude-code`,
`hermes`, `openclaw`). On success it writes `openclaw.json` plugin settings and
a management-stage plugin entrypoint under the OpenClaw config root. The plugin
entrypoint is a **runtime stub** until `@hm-arch/openclaw-plugin` is published;
OpenClaw will not load a working memory provider until that runtime ships.

## Memory modes

OpenClaw can run with several memory configurations. HM-Arch documentation and
benchmarks treat these as distinct modes:

| Mode | Description |
|------|-------------|
| **No memory** | OpenClaw runs without an active memory provider. Baseline for benchmarks. |
| **Native memory** | OpenClaw's built-in memory slot uses another provider already configured in OpenClaw. |
| **HM-Arch** | The HM-Arch memory plugin owns the OpenClaw memory slot and delegates durable storage to the Python sidecar. |
| **Mem0** | External Mem0 provider configured in OpenClaw instead of HM-Arch. |
| **OpenViking** | External OpenViking provider configured in OpenClaw instead of HM-Arch. |

HM-Arch install commands detect an occupied memory slot and refuse to overwrite
another provider silently. Switch providers explicitly in OpenClaw configuration
when you intend to replace Mem0, OpenViking, or another native backend.

## Install HM-Arch

**From PyPI**:

```bash
pip install hm-arch
# or:
pipx install hm-arch
```

**From npm** (pending MEM-74 — use Python CLI today):

```bash
# Not yet in the published @hm-arch/installer release:
# npx @hm-arch/installer install openclaw
```

Confirm the CLI:

```bash
hm-arch --help
```

## OpenClaw home

OpenClaw reads configuration from its home directory:

- `$OPENCLAW_HOME` when set, or
- `$OPENCLAW_STATE_DIR` / the default OpenClaw user config location for your platform

Use an isolated home for smoke tests:

```bash
export OPENCLAW_HOME=/tmp/hm-arch-smoke-openclaw
mkdir -p "$OPENCLAW_HOME"
```

## Connect OpenClaw

Recommended:

```bash
hm-arch install openclaw
```

This installs or updates:

- OpenClaw `plugins.slots.memory` set to `memory-hm-arch`
- `plugins.entries.memory-hm-arch` settings (`dbPath`, `sidecarCommand`, auto recall/capture)
- HM-Arch plugin manifest and entrypoint under `<config-root>/extensions/memory-hm-arch/`
- default SQLite database initialization

### Project vs global scope

Project-scoped configuration (default):

```bash
cd /path/to/your/workspace
hm-arch install openclaw
hm-arch status openclaw
```

User-global OpenClaw configuration:

```bash
hm-arch install openclaw --global
hm-arch status openclaw --global
```

After installation, **restart the OpenClaw gateway** so the running process
attempts to load the memory plugin.

## CLI exit behavior and integration state

Verified against `tests/test_integrations_openclaw_manage.py`:

| Command | Exit code | Integration state | Meaning |
|---------|-----------|-------------------|---------|
| `install openclaw` | `0` | `partial` | Config and plugin manifest written; runtime entrypoint is a stub. |
| `status openclaw` | `0` | `partial` | Slot active; warns about management-stage stub. |
| `doctor openclaw` | `1` | `partial` | Config valid but integration not fully ready (stub runtime or missing gateway restart). |
| `uninstall openclaw` | `0` | `not_installed` | HM-Arch config and plugin removed; database preserved. |

When the loadable `@hm-arch/openclaw-plugin` runtime is installed, `install` and
`status` report `installed` and `doctor` exits `0`.

Diagnostics to expect today:

- `openclaw.config.updated` — memory slot and plugin settings written
- `openclaw.plugin.installed` — manifest and stub entrypoint created
- `openclaw.plugin.runtime_stub` — entrypoint throws until runtime package ships
- `openclaw.gateway.restart` — gateway must be restarted after config changes

## Plugin behavior

The HM-Arch OpenClaw plugin (`openclaw.plugin.json`, memory kind) provides:

| Surface | Purpose |
|---------|---------|
| `memory_recall` tool | Explicit recall on demand |
| `memory_store` tool | Explicit durable capture |
| `memory_forget` tool | Targeted forgetting |
| `before_prompt_build` hook | Auto-recall before prompt assembly |
| `agent_end` hook | Auto-capture after agent completion (once per turn) |
| `session_end` hook | Session-end consolidation |

Recalled content is treated as **untrusted historical context**. Memory
failures are fail-open: recall/capture errors do not block agent responses.

### Sidecar protocol

The plugin talks to a persistent HM-Arch sidecar over JSONL stdio. Contract
version, operations, and golden fixtures live in
[docs/sidecar-protocol.md](../sidecar-protocol.md) and
`fixtures/sidecar-protocol/`. Core operations:

- `initialize`, `health`, `search`, `remember`, `forget`, `record_turn`,
  `consolidate`, `shutdown`

See [cross-agent benchmarks](../cross-agent-benchmarks.md) for telemetry fields
used in benchmark reports.

### Plugin configuration

Common plugin settings:

| Setting | Purpose |
|---------|---------|
| `dbPath` | SQLite database path for durable memory |
| `sidecarCommand` | argv prefix for the HM-Arch sidecar executable |
| `topK` | Maximum search results injected into context |
| `maxContextChars` | Upper bound on recalled context size |
| `autoRecall` | Enable `before_prompt_build` recall |
| `autoCapture` | Enable `agent_end` capture |

## Smoke test

```bash
export OPENCLAW_HOME=/tmp/hm-arch-smoke-openclaw
mkdir -p "$OPENCLAW_HOME"

hm-arch install openclaw
hm-arch status openclaw
hm-arch doctor openclaw   # exits 1 while runtime stub is present
```

Expected today (management stage):

- `install` exits `0` and prints `openclaw (project): partial`
- `status` reports `plugins.slots.memory is set to 'memory-hm-arch'`
- `doctor` exits `1` with `management-stage stub` warning
- SQLite database is created under the OpenClaw config root

After the loadable runtime ships and the gateway restarts:

- `status` reports `installed`
- `doctor` exits `0`

Inspect all agents:

```bash
hm-arch status
hm-arch doctor
```

Optional isolated cleanup:

```bash
hm-arch uninstall openclaw
hm-arch status openclaw
```

## Uninstall

```bash
hm-arch uninstall openclaw
```

Uninstall removes HM-Arch-owned plugin registration and sidecar wiring. It does
**not** delete existing SQLite memory databases. Remove database files manually
only after you no longer need stored memories.

Restart the OpenClaw gateway after uninstall so the previous memory provider
configuration is no longer cached in the running process.

## Database path

Default database location is under the OpenClaw workspace/home configured during
install. Override with plugin `dbPath` or `HM_ARCH_DB_PATH` when your deployment
requires a shared store across agents. See
[memory-sharing-policies.md](../memory-sharing-policies.md).

## Provider conflicts

If another memory provider already occupies the OpenClaw memory slot (for example
Mem0 or OpenViking), `status` and `doctor` report a conflict with remediation
text. HM-Arch never replaces another provider without an explicit configuration
change.

## Related docs

- [Agent installation guides](README.md)
- [Agent compatibility matrix](compatibility-matrix.md)
- [npm installer](../npm-installer.md)
- [Integration CLI smoke tests](../integration-cli-smoke.md)
- [Cross-agent memory benchmarks](../cross-agent-benchmarks.md)
- [Sidecar protocol](../sidecar-protocol.md)
- [Codex setup](codex.md)
- [Claude Code setup](claude-code.md)
- [Hermes setup](hermes.md)
