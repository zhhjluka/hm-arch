# README OpenClaw and Benchmark Results Design

## Goal

Update the repository README so users can install and verify the OpenClaw
integration from an isolated environment, and can understand the current state
of the LoCoMo, HotpotQA, and tau2-bench comparisons without mistaking smoke,
partial, unavailable, or unsupported cells for completed production results.

## Scope

Only `README.md` changes in the implementation. Existing benchmark artifacts and
OpenClaw integration code remain unchanged.

## OpenClaw Installation Verification

Extend the existing OpenClaw integration section with an isolated verification
flow:

1. Create temporary `HOME`, `OPENCLAW_STATE_DIR`, and project directories.
2. Install the project in editable development mode.
3. Run `hm-arch install openclaw`, `status`, and `doctor`.
4. Run the focused Python OpenClaw integration tests.
5. Run the OpenClaw plugin npm test suite.

The README will distinguish artifact-level verification from a real OpenClaw
gateway test. A gateway restart and live store/restart/recall check require an
installed OpenClaw CLI and are documented in `docs/openclaw-e2e-smoke.md`.

## Benchmark Presentation

Add a "Cross-Agent Benchmark Results" section with:

- A status table for LoCoMo, HotpotQA, and tau2-bench.
- Direct links to committed result artifacts and the methodology document.
- Numeric comparison claims only where committed real-CLI artifacts support
  them.
- Explicit warnings that mock/smoke results are not production comparisons.

The current evidence will be represented as follows:

| Benchmark | README treatment |
|-----------|------------------|
| LoCoMo | Report the real-CLI pilot scope and completion state. Do not claim a headline accuracy comparison because only the Hermes HM-Arch and no-memory cells completed, both at 0 normalized exact-match accuracy; other agent cells are partial, failed, or unavailable. |
| HotpotQA | Report the incomplete real-CLI pilot: 4 completed, 4 failed, 8 pending, and 24 unsupported cells. Include the artifact's aggregate pilot comparison for completed Codex and Claude Code cells: HM-Arch mean accuracy 0.60 vs no-memory 0.00; mean query time 4498.0 ms vs 8085.5 ms; mean input tokens 118282 vs 116956. |
| tau2-bench | Report the availability-only outcome. No cells are benchmark-eligible because tau2-bench was not importable and production agent CLIs were unavailable in the committed run. |

The README will state that LoCoMo uses normalized exact match rather than the
official category-aware token F1, and that the HotpotQA figures are pilot
aggregates rather than a complete matrix.

## Verification

- Validate every README command against the existing CLI and package scripts.
- Run the focused OpenClaw Python tests.
- Run `npm test` in `packages/openclaw-plugin`.
- Check Markdown links and inspect the final diff for consistency with the
  current README style.

## Non-Goals

- No version change, release, or package publication.
- No new benchmark run or artifact regeneration.
- No claims comparing HM-Arch with Mem0, OpenViking, or native memory where the
  committed matrix marks those cells unsupported or unavailable.
- No PRD change because this update documents already implemented and already
  accepted behavior; it does not change product requirements.
