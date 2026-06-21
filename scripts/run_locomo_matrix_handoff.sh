#!/usr/bin/env bash
# Run the LoCoMo real-CLI handoff matrix (MEM-78).
#
# Produces tracked artifacts under:
#   benchmarks/cross_agent/fixtures/locomo/handoff/
#
# Requires authenticated production CLIs on PATH or via env overrides:
#   HM_ARCH_BENCH_CODEX_EXECUTABLE
#   HM_ARCH_BENCH_CLAUDE_CODE_EXECUTABLE
#   HM_ARCH_BENCH_HERMES_EXECUTABLE
#   HM_ARCH_BENCH_OPENCLAW_EXECUTABLE
#
# Provider credentials (examples):
#   OPENAI_API_KEY or codex login        — Codex
#   ANTHROPIC_API_KEY or claude login    — Claude Code
#   OPENROUTER_API_KEY / hermes model    — Hermes
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HANDOFF_DIR="benchmarks/cross_agent/fixtures/locomo/handoff"
find "$HANDOFF_DIR" -mindepth 1 -maxdepth 1 -type d -name 'locomo-*' -exec rm -rf {} +
rm -f "$HANDOFF_DIR/matrix_summary.json" "$HANDOFF_DIR/matrix_summary_real.json"

export PATH="${HOME}/.npm-global/bin:${HOME}/.local/bin:${PATH}"

CODEX_EXE="${HM_ARCH_BENCH_CODEX_EXECUTABLE:-$(command -v codex || true)}"
CLAUDE_EXE="${HM_ARCH_BENCH_CLAUDE_CODE_EXECUTABLE:-$(command -v claude || true)}"
HERMES_EXE="${HM_ARCH_BENCH_HERMES_EXECUTABLE:-$(command -v hermes || true)}"
OPENCLAW_EXE="${HM_ARCH_BENCH_OPENCLAW_EXECUTABLE:-$(command -v openclaw || true)}"

echo "Handoff CLIs:"
args=(
  uv run python scripts/run_locomo_matrix.py
  --handoff \
  --runner-mode real \
  --include-openclaw \
  --dataset-id locomo10-sample \
  --dataset-version 2024-03-sample \
  --max-conversations 1 \
  --max-queries "${LOCOMO_HANDOFF_MAX_QUERIES:-5}" \
  --agent-timeout-s "${LOCOMO_AGENT_TIMEOUT_S:-90}"
)

for spec in \
  "codex:$CODEX_EXE:--codex-executable" \
  "claude:$CLAUDE_EXE:--claude-code-executable" \
  "hermes:$HERMES_EXE:--hermes-executable" \
  "openclaw:$OPENCLAW_EXE:--openclaw-executable"; do
  IFS=: read -r name executable flag <<< "$spec"
  if [[ -n "$executable" ]]; then
    echo "  $name: $executable ($("$executable" --version 2>/dev/null | head -1 || echo version-unavailable))"
    args+=("$flag" "$executable")
  else
    echo "  $name: unavailable (recorded in matrix)"
  fi
done

"${args[@]}"

echo
echo "Wrote handoff artifacts to $HANDOFF_DIR/"
