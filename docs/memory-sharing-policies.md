# Memory sharing and isolation policies

HM-Arch separates **global** (user-wide) and **project** (repository-local) SQLite
stores. Export, import, and migration commands help you move data between stores
without losing provenance or breaking isolation rules from MEM-53–MEM-55.

## Recommended defaults

| Data type | Store | Provenance |
|-----------|-------|------------|
| User preferences that apply across repos | Global | `provenance_project` unset |
| Repository facts, decisions, and runbooks | Project | `provenance_project` set to the repo path |
| Agent/session attribution | Either | `provenance_agent`, `provenance_session`, `memory_type` |

Keep **project-private** content in the project store. Only place memories in the
global store when another repository should legitimately recall them (for example
editor theme or language preferences).

## CLI commands

```bash
# Export the active project database
hm-arch memory export -o ./backup/project-memories.json --scope project

# Export the global user database
hm-arch memory export -o ./backup/global-memories.json --scope global \
  --db ~/.hm-arch/global.db

# Import into a project store (validates scope and project isolation)
hm-arch memory import ./backup/project-memories.json --target-scope project \
  --project-context "$(pwd)"

# Split a legacy single-file database into global + project stores
hm-arch memory migrate --from ./.hm_arch_agent_memory.db \
  --global-db ~/.hm-arch/global.db \
  --project-db ./.hm-arch/memory.db \
  --project-context "$(pwd)"
```

Environment variables `HM_ARCH_PROJECT_DB_PATH`, `HM_ARCH_GLOBAL_DB_PATH`, and
`HM_ARCH_DB_PATH` follow the same resolution order as adapter hooks (see
`IntegrationConfig.resolve_db_path`).

## Import safety rules

Imports **reject** unsafe operations by default:

1. **Scope remap** — An export tagged `project` cannot be imported into the global
   store unless you pass `--allow-scope-remap` (and usually should not).
2. **Project-tagged global import** — Rows with `provenance_project` cannot enter
   the global store unless you pass `--allow-cross-scope`.
3. **Cross-project leakage** — Project-scoped imports require matching
   `--project-context` (default: current working directory). Memories tagged for
   another project path are rejected.
4. **Malformed provenance** — Control characters or oversized provenance fields
   are rejected before any write occurs.
5. **Referential integrity** — Child rows (`episodes`, `semantics`, `review_queue`)
   must reference `memory_id` values present in the bundle.

Use `--mode merge` (default) to skip rows whose primary keys already exist, or
`--mode replace` to overwrite destination rows (destructive).

## Migration from a single database

`hm-arch memory migrate` partitions a legacy database as follows:

- Rows with **no** `provenance_project` → global store (user-wide memories).
- Rows whose `provenance_project` matches `--project-context` → project store.
- Rows tagged for **other** projects → migration fails with an explicit error.

Skills, meta-memory keys, and consolidation logs are copied only into the
project store because they are typically repository-specific operational state.

Run with `--dry-run` to preview counts before writing files.

## Sharing between agents

Cross-agent recall (Codex, Claude Code, Hermes) uses the same stores and
provenance columns. When sharing:

- Record `agent` and `session` on `hm-arch record` / `HMArch.add` so search
  results remain explainable.
- Use global scope only for portable user preferences.
- Rely on project isolation in cross-store search so unrelated repositories do
  not see private memories (see `search_cross_stores`).

Concurrent access to the same SQLite file from multiple agent processes on one
machine is supported via WAL mode, busy timeouts, and bounded lock retries.
See [storage-concurrency.md](./storage-concurrency.md) for configuration and
limitations.

## Out of scope

These commands operate on local SQLite files only. There is **no** cloud sync,
multi-user merge, or automatic conflict resolution across machines.
