# HM-Arch Phase 2 Plan

## Goal

Complete the full seven-layer HM-Arch memory loop and prepare the SDK for real
agent integration and release.

## Scope

Phase 1 delivered the MVP memory loop: storage, vector fallback, L0-L3, add,
search, forgetting math, basic consolidation, stats, context manager, examples,
and docs.

Phase 2 adds:

- L4 episodic long-term archive
- L5 procedural memory
- L6 meta memory
- Full sleep consolidation
- Codex and Claude Code hook examples
- 30-day simulation tests
- Release readiness and PyPI preparation

## Execution Order

1. HM-18: Implement L4 episodic long-term archive
2. HM-19: Wire L4 into search and consolidation
3. HM-20: Implement L5 procedural memory
4. HM-21: Implement L6 meta memory
5. HM-22: Full sleep consolidation cycle
6. HM-23: Codex and Claude Code hook examples
7. HM-24: End-to-end 30-day simulation tests
8. HM-25: Release readiness and PyPI prep

## Cursor Delegation Rules

Each issue should be dispatched to Cursor as one bounded PR.

Dispatch uses the single-trigger rule:

- keep labels `offline-tests`, `codex-review`, and `cursor-ready`
- move the issue to `In Progress`
- do not set Linear `delegate` to Cursor
- post one complete `@Cursor please implement ...` comment

Every Cursor issue must include:

- Files to create or modify
- Explicit out-of-scope notes
- A single suggested `uv run pytest ...` command
- Requirement to keep tests offline
- Requirement to avoid mandatory external LLM/API keys
- Requirement to leave a completion comment with changed files and commands run

Codex owns:

- Contract review against PRD and `docs/spec.md`
- Running the full test suite before merge
- Updating Linear/GitHub status
- Dispatching the next issue after merge using the single `@Cursor` comment trigger

## Quality Gates

Before each merge:

- `uv run pytest` must pass
- Public API changes must be reflected in tests
- Storage schema changes must be asserted by exact-column tests
- No mandatory external services may be introduced
- Scope must match the issue; unrelated refactors are rejected

## Phase 2 Completion Criteria

Phase 2 is complete when:

- L4/L5/L6 are implemented and reachable through stable APIs
- Consolidation performs replay, semantic extraction, conflict handling, review scheduling, and L4 archiving
- Agent hook examples run offline
- 30-day simulation tests pass
- Release checklist is ready
- PyPI publishing is prepared but not executed without explicit approval
