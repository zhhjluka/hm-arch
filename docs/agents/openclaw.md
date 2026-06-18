# OpenClaw setup (HM-Arch)

> **Availability:** OpenClaw install commands ship with the HM-65 integration
> release (CLI handler, memory plugin, and npm installer support). On earlier
> releases, `hm-arch install openclaw` is not yet registered; use Codex, Claude
> Code, or Hermes commands documented in the main README.

Install HM-Arch as OpenClaw's native memory provider. OpenClaw integration uses
a TypeScript memory plugin (`packages/openclaw-plugin/`) backed by a persistent
Python sidecar that exposes HM-Arch recall, capture, forget, and consolidation
without per-query process startup.

All management commands are offline and do not require LLM/API keys. The sidecar
uses the same SQLite-backed HM-Arch runtime as Codex, Claude Code, and Hermes.

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

**From npm** (Python-free path when standalone artifacts are available):

```bash
npm install -g @hm-arch/installer
hm-arch-install install openclaw
```

One-shot:

```bash
npx @hm-arch/installer install openclaw
```

Confirm the CLI:

```bash
hm-arch --help
# or, after npm install:
hm-arch-install --help
```

## OpenClaw home

OpenClaw reads configuration from its home directory:

- `$OPENCLAW_HOME` when set, or
- the default OpenClaw user config location for your platform

Use an isolated home for smoke tests:

```bash
export OPENCLAW_HOME=/tmp/hm-arch-smoke-openclaw
mkdir -p "$OPENCLAW_HOME"
```

## Connect OpenClaw

Recommended:

```bash
hm-arch install openclaw
# or:
hm-arch-install install openclaw
```

This installs or updates:

- the HM-Arch OpenClaw memory plugin package
- OpenClaw plugin registration for the memory slot
- sidecar executable discovery (standalone binary or managed Python runtime)
- default SQLite database path under the OpenClaw workspace/home

### Project vs global scope

Where OpenClaw permits project-scoped configuration:

```bash
cd /path/to/your/workspace
hm-arch install openclaw
hm-arch status openclaw
```

For user-global OpenClaw configuration:

```bash
hm-arch install openclaw --global
hm-arch status openclaw --global
```

After installation, **restart the OpenClaw gateway** so the running process
loads the memory plugin and sidecar manager.

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
version, operations, and golden fixtures live under
`src/hm_arch/integrations/openclaw/` and shared protocol fixtures. Core
operations:

- `initialize`, `health`, `search`, `remember`, `forget`, `record_turn`,
  `consolidate`, `shutdown`

See [cross-agent benchmarks](../cross-agent-benchmarks.md) for telemetry fields
used in benchmark reports (query latency, hit count, returned characters, storage
latency).

### Plugin configuration

Common plugin settings:

| Setting | Purpose |
|---------|---------|
| `dbPath` | SQLite database path for durable memory |
| `topK` | Maximum search results injected into context |
| `maxContextChars` | Upper bound on recalled context size |
| `autoRecall` | Enable `before_prompt_build` recall |
| `autoCapture` | Enable `agent_end` capture |
| consolidation behavior | Session-end `consolidate` scheduling |

## Smoke test

```bash
export OPENCLAW_HOME=/tmp/hm-arch-smoke-openclaw
mkdir -p "$OPENCLAW_HOME"

hm-arch install openclaw
hm-arch status openclaw
hm-arch doctor openclaw
```

Expected when fully configured:

- `status` reports `installed` with memory-plugin roles
- `doctor` exits 0 when plugin package, sidecar executable, config, and storage
  permissions are valid
- `doctor` warns when the gateway must be restarted after config changes

Inspect all agents:

```bash
hm-arch status
hm-arch doctor
```

### Lifecycle verification

After gateway restart:

1. Store a memory through a normal agent turn or `memory_store`
2. Restart the gateway and confirm recall still returns the stored item
3. Confirm `before_prompt_build` injects bounded recalled context
4. Confirm `agent_end` captures exactly once per completed turn
5. Confirm `session_end` triggers consolidation when enabled

Optional isolated cleanup:

```bash
hm-arch uninstall openclaw
hm-arch status openclaw
```

## Uninstall

```bash
hm-arch uninstall openclaw
# or:
hm-arch-install uninstall openclaw
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
- [Codex setup](codex.md)
- [Claude Code setup](claude-code.md)
- [Hermes setup](hermes.md)
