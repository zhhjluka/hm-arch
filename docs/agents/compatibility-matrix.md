# Agent compatibility matrix

HM-Arch integrates with four coding agents. This matrix summarizes what the
packaged `hm-arch` CLI supports today and where manual configuration is
required.

## Summary

| Capability | Codex | Claude Code | Hermes | OpenClaw |
|------------|:-----:|:-----------:|:------:|:--------:|
| Hook / plugin install via `hm-arch install` | Yes | Yes | Yes (native plugin bridge) | Yes (memory plugin config; `partial` until runtime ships) |
| `hm-arch status` / `doctor` | Yes | Yes | Yes | Yes |
| `hm-arch doctor --fix` (safe config repair) | Yes | Yes | No | No |
| Recall / record / consolidate hooks | Yes | Yes | Via plugin | Via plugin + sidecar (when runtime loads) |
| Project-scoped memory | Yes | Yes | Yes | Yes |
| Global-scoped memory | Yes | Yes | Yes | Yes (`--global`) |
| Shared database with other agents | Yes | Yes | Yes | Yes |
| Offline operation (no API keys) | Yes | Yes | Yes | Yes (management CLI) |
| npm `hm-arch-install install` | Yes | Yes | Yes | Pending (MEM-74) |

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
| Install / uninstall via CLI | Supported | `hm-arch install openclaw` / `uninstall openclaw` |
| Project vs global scope | Supported | Default project; `--global` for user OpenClaw state |
| Status / doctor | Supported | Reports `partial` while plugin entrypoint is a management stub |
| Doctor `--fix` | **Not supported** | Re-run `install` after fixing config permissions |
| Runtime plugin load | **Partial** | Stub entrypoint until `@hm-arch/openclaw-plugin` ships |
| Memory slot conflict | Detected | Another `plugins.slots.memory` provider blocks install |
| npm `hm-arch-install` | **Pending** | MEM-74; use Python CLI today |
| Missing `openclaw` CLI | Warning only | Config inspection still works via `OPENCLAW_HOME` |

## Memory backends (cross-agent benchmarks)

| Backend | Codex | Claude Code | Hermes | OpenClaw |
|---------|:-----:|:-----------:|:------:|:--------:|
| No memory | ✓ | ✓ | ✓ | ✓ |
| Native memory | ✓ | ✓ | ✓ | ✓ |
| HM-Arch | ✓ | ✓ | ✓ | ✓* |
| Mem0 | unsupported | unsupported | ✓† | ✓† |
| OpenViking | unsupported | unsupported | unsupported | ✓† |

\* OpenClaw × HM-Arch live benchmarks are `unavailable` while the plugin runtime
stub is present.

† Requires external package; offline runs are `mock-only`, not `real`.

See [cross-agent-benchmarks.md](../cross-agent-benchmarks.md) for
`real` / `mock-only` / `unavailable` / `unsupported` reporting rules.

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
- [Integration CLI smoke tests](../integration-cli-smoke.md)
- [Memory sharing policies](../memory-sharing-policies.md)
- [Storage concurrency](../storage-concurrency.md)
