# HM-Arch v2.0.4

HM-Arch **2.0.4** is a patch release for the four-agent integration line. It
keeps the v2.0.x Python, npm, OpenClaw plugin, and standalone channels aligned
while making the default user-facing install path use the latest stable package.

## What changed

- Codex recall hook output now includes
  `hookSpecificOutput.hookEventName: "UserPromptSubmit"` alongside
  `additionalContext`, matching the expected lifecycle hook JSON shape.
- Hermes, Claude Code, Codex, and OpenClaw installation and memory smoke paths
  were validated together after the v2.0.x integration fixes.
- README and agent setup docs now recommend latest stable install commands for
  normal users:

```bash
pip install hm-arch
pipx install hm-arch
npm install -g @hm-arch/installer
npx @hm-arch/installer install hermes
npx @hm-arch/installer install claude-code
npx @hm-arch/installer install codex
npx @hm-arch/installer install openclaw
```

Version-pinned installs remain supported when users need reproducible
environments:

```bash
pip install hm-arch==2.0.4
npm install -g @hm-arch/installer@2.0.4
```

## OpenClaw integration

- `hm-arch install openclaw` / `npx @hm-arch/installer install openclaw` register
  `@hm-arch/openclaw-plugin`, configure `plugins.slots.memory`, and start the
  Python sidecar command.
- OpenClaw peer dependency: `openclaw >= 2026.6.0` (validated against 2026.6.8 in
  plugin dev tests).
- Restart the OpenClaw gateway after install or uninstall so the memory plugin
  reloads. See [docs/agents/openclaw.md](agents/openclaw.md).

## Cross-agent benchmark setup

Committed pilot artifacts and methodology:

| Dataset | Committed artifact | Status |
|---------|-------------------|--------|
| LoCoMo | `benchmarks/cross_agent/fixtures/locomo/handoff/matrix_summary_real.json` | Real-CLI pilot (1 conversation, 3 queries/cell) |
| HotpotQA | *(local only)* `benchmark-results/hotpotqa/` | Harness ready; no committed production matrix |
| tau2-bench | *(local only)* `benchmark-results/tau2-comparison/` | Harness ready; no committed production matrix |

Reproduce the LoCoMo handoff:

```bash
scripts/run_locomo_matrix_handoff.sh
```

Offline harness smoke (not production comparison):

```bash
python scripts/run_hotpotqa_matrix.py --smoke
python scripts/run_tau2_bench_comparison.py --smoke
```

## Known limitations

- **LoCoMo pilot metric** — normalized exact match, not official LoCoMo
  category-aware token F1. Do not compare pilot `mean_accuracy` to academic
  leaderboard scores.
- **LoCoMo pilot scope** — committed real-CLI cells may be `completed`,
  `failed`, `partial`, or `unavailable`. Only `completed` cells with
  `runner_mode=real` and `test_double_mode=false` support headline comparison
  claims. OpenClaw cells in the committed pilot are `unavailable` when the
  OpenClaw CLI is absent on the host.
- **HotpotQA / tau2-bench** — runners and matrix schema are shipped, but
  production comparison artifacts are not committed in this release. Do not
  publish headline numbers without a corresponding artifact directory.
- **Published standalone v2.0.4** — GitHub Release standalone binaries predating
  OpenClaw wiring do not include `openclaw` in `hm-arch install` choices. Use the
  Python/npm path (`HM_ARCH_RUNTIME=python`) or rebuild standalone from this
  commit until the next coordinated release rebuilds binaries.
- **Provider credentials** — real agent CLI benchmarks require agent-specific
  API keys or login; failed cells are recorded explicitly and excluded from
  completed-query aggregates.

## Verification

Release verification before tagging:

```bash
pytest
python examples/release_smoke.py
python scripts/verify_release_versions.py
python scripts/validate_release_gate.py
cd packages/installer && npm test
cd packages/openclaw-plugin && npm test
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
- Supported standalone npm targets: linux x86_64/aarch64, darwin arm64, windows
  x86_64
