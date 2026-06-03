# HM-Arch Phase 3 Plan

## Goal

Complete the original PRD's externally visible contract while preserving the
offline-first, zero-required-service behavior established in Phase 1 and Phase 2.

Phase 3 turns the existing layer implementations into a complete product loop:
public API compatibility, seven-layer facade integration, automatic lifecycle
management, optional provider backends, scale validation, and a GitHub Release.

## Product Decisions

- The original PRD remains the target contract for public behavior.
- Local deterministic implementations remain the default and must work without
  API keys, network access, ChromaDB, or other mandatory services.
- LLM, embedding, and ChromaDB support are optional backends.
- HM-Arch will not be published to PyPI in Phase 3.
- Release distribution is through a versioned GitHub Release with locally built
  wheel and sdist artifacts attached when appropriate.

## Execution Order

1. HM-26: Complete the public API contract
2. HM-27: Complete the seven-layer facade integration
3. HM-28: Implement forgetting controller and automatic lifecycle
4. HM-29: Implement memory strength modulation
5. HM-30: Add optional provider and vector backends
6. HM-31: Validate PRD scale and performance
7. HM-32: Prepare and publish the GitHub v1.0.0 release

## Cursor Delegation Rules

Each issue is one bounded Cursor PR. Use the single-trigger workflow:

- keep labels `offline-tests`, `codex-review`, and `cursor-ready`
- move the issue to `In Progress`
- leave Linear delegate unset
- post exactly one complete `@Cursor please implement ...` comment
- require issue-specific tests plus `uv run pytest`

Requested-fixes comments that expect Cursor to continue work must include
`@Cursor` because Linear delegate remains unset.

## Quality Gates

Before each merge:

- The issue-specific test command passes.
- `uv run pytest` passes.
- Public behavior is checked against the original PRD and `docs/spec.md`.
- Offline behavior remains the default.
- Optional backends degrade cleanly when dependencies or credentials are absent.
- No unrelated refactors or mandatory external services are introduced.

## Phase 3 Completion Criteria

Phase 3 is complete when:

- The public `HMArch` API matches the supported PRD contract.
- L0-L6 are reachable through stable facade APIs or documented public layer APIs,
  and cross-layer statistics are accurate.
- Forgetting, consolidation scheduling, capacity enforcement, and conservative
  physical cleanup form a complete lifecycle.
- Importance and memory strength modulation affect retention behavior.
- Optional LLM, embedding, and ChromaDB backends are available without weakening
  the local fallback.
- PRD scale and performance claims have reproducible benchmark evidence.
- A GitHub `v1.0.0` Release is published with release notes and verified build
  artifacts.
- No PyPI publishing is performed.
