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
#
# Provider credentials (examples):
#   OPENAI_API_KEY or codex login        — Codex
#   ANTHROPIC_API_KEY or claude login    — Claude Code
#   OPENROUTER_API_KEY / hermes model    — Hermes
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export PATH="${HOME}/.npm-global/bin:${HOME}/.local/bin:${PATH}"

CODEX_EXE="${HM_ARCH_BENCH_CODEX_EXECUTABLE:-$(command -v codex || true)}"
CLAUDE_EXE="${HM_ARCH_BENCH_CLAUDE_CODE_EXECUTABLE:-$(command -v claude || true)}"
HERMES_EXE="${HM_ARCH_BENCH_HERMES_EXECUTABLE:-$(command -v hermes || true)}"

if [[ -z "$CODEX_EXE" || -z "$CLAUDE_EXE" || -z "$HERMES_EXE" ]]; then
  echo "error: install codex, claude, and hermes CLIs before running handoff" >&2
  echo "  codex:  npm install -g @openai/codex" >&2
  echo "  claude: npm install -g @anthropic-ai/claude-code" >&2
  echo "  hermes: curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash" >&2
  exit 1
fi

echo "Handoff CLIs:"
echo "  codex:  $CODEX_EXE ($("$CODEX_EXE" --version 2>/dev/null | head -1 || echo version-unavailable))"
echo "  claude: $CLAUDE_EXE ($("$CLAUDE_EXE" --version 2>/dev/null | head -1 || echo version-unavailable))"
echo "  hermes: $HERMES_EXE ($("$HERMES_EXE" --version 2>/dev/null | head -1 || echo version-unavailable))"

python3 scripts/run_locomo_matrix.py \
  --handoff \
  --runner-mode real \
  --dataset-id locomo10-sample \
  --dataset-version 2024-03-sample \
  --max-conversations 1 \
  --max-queries "${LOCOMO_HANDOFF_MAX_QUERIES:-5}" \
  --codex-executable "$CODEX_EXE" \
  --claude-code-executable "$CLAUDE_EXE" \
  --hermes-executable "$HERMES_EXE" \
  --agent-timeout-s "${LOCOMO_AGENT_TIMEOUT_S:-90}"

echo
echo "Wrote handoff artifacts to benchmarks/cross_agent/fixtures/locomo/handoff/"
