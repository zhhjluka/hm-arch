# OpenClaw release readiness (MEM-79)

Validation findings for the OpenClaw integration line and cross-agent benchmark
pilots. This document is **unversioned** — it records readiness evidence while
the repository remains at the current public release (**v2.0.4**). Version
selection and publication require separate maintainer instruction.

## Integration scope

- `hm-arch install openclaw` / `npx @hm-arch/installer install openclaw` register
  `@hm-arch/openclaw-plugin`, configure `plugins.slots.memory`, and start the
  Python sidecar command.
- OpenClaw peer dependency: `openclaw >= 2026.6.0` (validated against 2026.6.8 in
  plugin dev tests).
- Restart the OpenClaw gateway after install or uninstall so the memory plugin
  reloads. See [agents/openclaw.md](agents/openclaw.md).

## Cross-agent benchmark pilots

| Dataset | Git-tracked artifact | Pilot status |
|---------|---------------------|--------------|
| LoCoMo | `benchmarks/cross_agent/fixtures/locomo/handoff/matrix_summary_real.json` | Real-CLI pilot (1 conversation, 3 queries/cell) |
| HotpotQA | `benchmark-results/hotpotqa/matrix_summary.json` | Incomplete pilot (4 completed / 4 failed / 8 pending / 24 unsupported) |
| tau2-bench | `benchmark-results/tau2-comparison/` | Availability record (`tau2_importable=false`; no completed real cells) |

Reproduce the LoCoMo handoff:

```bash
scripts/run_locomo_matrix_handoff.sh
```

Offline harness smoke (not production comparison):

```bash
python scripts/run_hotpotqa_matrix.py --smoke
python scripts/run_tau2_bench_comparison.py --smoke
```

Methodology and schema details: [cross-agent-benchmarks.md](cross-agent-benchmarks.md).

## Known limitations

- **LoCoMo pilot metric** — normalized exact match, not official LoCoMo
  category-aware token F1. Do not compare pilot `mean_accuracy` to academic
  leaderboard scores.
- **LoCoMo pilot scope** — committed real-CLI cells may be `completed`,
  `failed`, `partial`, or `unavailable`. Only `completed` cells with
  `runner_mode=real` and `test_double_mode=false` support headline comparison
  claims. OpenClaw cells in the committed pilot are `unavailable` when the
  OpenClaw CLI is absent on the host.
- **HotpotQA pilot** — committed artifact records partial real-CLI runs using
  `status=run` rows. Derive completed vs failed from `completed_query_count` and
  `total_failure_count` (4 completed / 4 failed / 8 pending / 24 unsupported in
  the committed pilot). Do not publish headline retrieval comparisons outside
  that incomplete pilot context.
- **tau2-bench pilot** — committed artifact is an availability record when
  `tau2_importable` is false or agent CLIs are absent. Do not present
  `summary_table.json` rows as successful benchmark comparisons.
- **Provider credentials** — real agent CLI benchmarks require agent-specific
  API keys or login; failed cells are recorded explicitly and excluded from
  completed-query aggregates.

## Readiness verification

Default release-readiness gate (no target version):

```bash
pytest
python examples/release_smoke.py
python scripts/verify_release_versions.py
python scripts/validate_release_gate.py
cd packages/installer && npm test
cd packages/openclaw-plugin && npm test
```

Release-time gate (only after maintainer selects a version):

```bash
python scripts/validate_release_gate.py --target-version X.Y.Z
```

Clean-machine npm verification (no Python on PATH at test time):

```bash
python scripts/build_standalone.py --clean
export HM_ARCH_STANDALONE_FIXTURE=dist/standalone/hm-arch
cd packages/installer && node ./scripts/run-clean-machine-tests.mjs
```

## Compatibility

- Python: 3.10+
- Node.js: 18+
- Supported agents: Codex, Claude Code, Hermes, OpenClaw
- OpenClaw CLI: `>= 2026.6.0` (peer dependency on `@hm-arch/openclaw-plugin`)
