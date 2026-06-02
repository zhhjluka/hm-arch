# Cursor + Codex Workflow

## Operating Model

Linear is the dispatcher. Cursor should receive small issues with explicit acceptance criteria. Codex owns architecture, integration, review, and test verification.

Linear project:

- HM-Arch MVP: https://linear.app/mem-as-human/project/hm-arch-mvp-4d6d317320cb

## How Cursor Should Work

For each issue:

1. Read `docs/spec.md` and the issue description.
2. Modify only the files required by the issue.
3. Add or update tests for public behavior.
4. Run the issue's test command.
5. Leave a concise completion note with changed files, tests run, and any ambiguity.

Cursor should not:

- Change MVP scope.
- Add mandatory external services.
- Make LLM/API keys required for tests.
- Implement unrelated layers while solving a narrow issue.
- Delete user or Codex changes.

## How Codex Should Work

Codex should:

- Keep `docs/spec.md` and `docs/tasks.md` aligned with Linear.
- Review Cursor output issue by issue.
- Run tests after each meaningful integration point.
- Fix cross-module wiring when multiple Cursor issues meet.
- Escalate only true product decisions to Luka.

## Cursor Dispatch Rule

Use exactly one Cursor trigger per issue.

Preferred dispatch pattern:

1. Keep the issue labels: `offline-tests`, `codex-review`, `cursor-ready`.
2. Move the issue to `In Progress`.
3. Do **not** set Linear `delegate` to Cursor.
4. Add one complete `@Cursor please implement ...` comment with scope,
   acceptance criteria, out-of-scope notes, and verification commands.

Rationale:

- Setting Linear `delegate = Cursor` and also posting an `@Cursor` comment can
  start two Cursor Cloud Agent jobs for the same issue.
- The `@Cursor` comment is the single source of execution instructions.
- If duplicate PRs still appear, Codex reviews both and keeps the better one.

## Linear Issue Template

```md
Context:
HM-Arch is a Python SDK for human-like agent memory. This issue implements one bounded slice of the MVP.

Scope:
- ...

Acceptance:
- ...

Out of scope:
- ...

Test command:
pytest ...

Cursor notes:
- Work only inside the files implied by this issue.
- Keep all tests offline.
- Leave a comment if product behavior is ambiguous.
```

## Milestones

- M0: Project Scaffold
- M1: Storage Foundation
- M2: Add/Search MVP
- M3: Forgetting and Consolidation
- M4: Developer Experience

## First Delegation Recommendation

Start Cursor with `MEM-6: HM-1 Scaffold Python package`, then `MEM-7: HM-2 Implement public types and config`.

These issues have small scope, low ambiguity, and create a stable base for later parallel work.

Initial issue queue:

- MEM-6: HM-1 Scaffold Python package
- MEM-7: HM-2 Implement public types and config
- MEM-8: HM-3 Implement SQLite storage
- MEM-9: HM-4 Implement vector store abstraction with local fallback
- MEM-10: HM-5 Implement L0 and L1 memory layers
- MEM-11: HM-6 Implement L2 episodic buffer
- MEM-12: HM-7 Implement L3 semantic memory
- MEM-13: HM-8 Implement HMArch facade add/search
- MEM-14: HM-9 Implement forgetting math
- MEM-15: HM-10 Implement basic consolidation
- MEM-16: HM-11 Implement stats, context manager, and examples
- MEM-17: HM-12 Integration pass and docs
