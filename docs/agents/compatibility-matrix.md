# Agent compatibility matrix

HM-Arch integrates with four coding agents. This matrix summarizes what the
packaged `hm-arch` CLI supports today and where manual configuration is
required.

## Summary

| Capability | Codex | Claude Code | Hermes | OpenClaw |
|------------|:-----:|:-----------:|:------:|:--------:|
| Hook install via `hm-arch install` | Yes | Yes | Yes (native plugin bridge) | Yes (memory plugin + sidecar) |
| `hm-arch status` / `doctor` | Yes | Yes | Yes | Yes |
| `hm-arch doctor --fix` (safe config repair) | Yes | Yes | No | Yes (HM-Arch-owned config only) |
| Recall / record / consolidate hooks | Yes | Yes | Via plugin | Via plugin hooks + tools |
| Project-scoped memory | Yes | Yes | Yes | Yes |
| Global-scoped memory | Yes | Yes | Yes | Yes (where OpenClaw permits) |
| Shared database with other agents | Yes | Yes | Yes | Yes |
| Offline operation (no API keys) | Yes | Yes | Yes | Yes |

## Memory backend comparison

Cross-agent benchmarks and integration docs use five memory modes. Support
depends on agent capabilities and installed providers:

| Mode | Codex | Claude Code | Hermes | OpenClaw |
|------|:-----:|:-----------:|:------:|:--------:|
| No memory | Baseline (`--disable memories`) | Baseline | `memory.provider` unset / disabled | Memory slot empty |
| Native memory | Codex file-backed memories | Claude Code native context | Hermes default provider | OpenClaw native slot |
| HM-Arch | `.codex` hooks | `.claude` hooks | `memory.provider: hm-arch` | HM-Arch memory plugin |
| Mem0 | N/A (external) | N/A (external) | `memory.provider: mem0` | OpenClaw Mem0 provider |
| OpenViking | N/A (external) | N/A (external) | Provider-specific | OpenClaw OpenViking provider |

See [cross-agent-benchmarks.md](../cross-agent-benchmarks.md) for the full
benchmark matrix and metric definitions.

## Codex

| Feature | Support | Notes |
|---------|---------|-------|
| Install / uninstall hooks | Supported | `hm-arch install codex` / `uninstall codex` |
| Project vs global scope | Supported | Default project; `--global` for `~/.codex` |
| Doctor diagnostics | Supported | Hooks, `config.toml` feature flag, executables |
| Doctor `--fix` | Supported | Re-installs partial hooks and re-enables `[features].hooks` |
| Missing `hm-arch` on PATH | Degraded | Hooks fall back to `python -m hm_arch.integrations.cli` |
| Missing `codex` CLI | Warning only | Hooks still run when Codex invokes them |

## Claude Code

| Feature | Support | Notes |
|---------|---------|-------|
| Install / uninstall hooks | Supported | `hm-arch install claude-code` |
| Project vs global scope | Supported | Default project; `--global` for user settings |
| Doctor diagnostics | Supported | Hooks, executables, config directory |
| Doctor `--fix` | Supported | Re-installs partial hook sets |
| Missing `hm-arch` on PATH | Degraded | Same Python module fallback as Codex |
| Missing `claude` CLI | Warning only | Does not block hook execution |

## Hermes

| Feature | Support | Notes |
|---------|---------|-------|
| Install / uninstall via CLI | Supported | Writes Hermes `config.yaml`, plugin bridge, and HM-Arch database |
| Status / doctor | Supported | Inspects `memory.provider`, plugin settings, conflicts |
| Doctor `--fix` | **Not supported** | Provider conflicts and YAML edits require manual changes |
| `memory.provider: mem0` conflict | Detected | Doctor reports error; user must switch provider explicitly |
| Database path override | Supported | `plugins.hm-arch.db_path` in Hermes config |
| Missing `hermes` CLI | Warning only | Config inspection still works via `HERMES_HOME` |

## OpenClaw

| Feature | Support | Notes |
|---------|---------|-------|
| Install / uninstall via CLI | Supported | Installs memory plugin, sidecar wiring, and default database path |
| Status / doctor | Supported | Plugin package, sidecar executable, config, storage permissions |
| Doctor `--fix` | Supported | Re-installs HM-Arch-owned partial plugin configuration only |
| Memory slot conflict | Detected | Mem0, OpenViking, or other providers must be switched explicitly |
| Gateway restart required | Yes | Restart OpenClaw gateway after install/uninstall/config changes |
| Persistent sidecar | Supported | JSONL stdio protocol; fail-open on recall/capture errors |
| Tools | Supported | `memory_recall`, `memory_store`, `memory_forget` |
| Hooks | Supported | `before_prompt_build`, `agent_end`, `session_end` |
| Missing `openclaw` CLI | Warning only | Config inspection still works via `OPENCLAW_HOME` |

## Recovery commands (all agents)

These commands operate on the configured SQLite stores and are agent-agnostic:

| Command | Purpose |
|---------|---------|
| `hm-arch memory backup -o <dir>` | Filesystem copy of `.db`, `-wal`, and `-shm` |
| `hm-arch memory restore <dir> --confirm` | Restore from backup (requires explicit confirmation) |
| `hm-arch memory repair` | `PRAGMA integrity_check`, schema migration, optional `VACUUM` |
| `hm-arch memory export` / `import` | Portable JSON transfer between stores |
| `hm-arch doctor` | Integration + storage diagnostics (permissions, integrity) |

Destructive operations (overwrite restore, provider switches) always require
explicit user confirmation or manual configuration edits.

## Related docs

- [Agent installation guides](README.md)
- [OpenClaw setup](openclaw.md)
- [Integration CLI smoke tests](../integration-cli-smoke.md)
- [Cross-agent memory benchmarks](../cross-agent-benchmarks.md)
- [Memory sharing policies](../memory-sharing-policies.md)
- [Storage concurrency](../storage-concurrency.md)
