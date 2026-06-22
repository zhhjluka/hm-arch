# HM-Arch v2.0.4

HM-Arch **2.0.4** is a patch release for the three-agent integration line. It
keeps the v2.0.x Python, npm, and standalone channels aligned while making the
default user-facing install path use the latest stable package.

## What changed

- Codex recall hook output now includes
  `hookSpecificOutput.hookEventName: "UserPromptSubmit"` alongside
  `additionalContext`, matching the expected lifecycle hook JSON shape.
- Hermes, Claude Code, and Codex installation and memory smoke paths were
  validated together after the v2.0.x integration fixes.
- README and agent setup docs now recommend latest stable install commands for
  normal users:

```bash
pip install hm-arch
pipx install hm-arch
npm install -g @hm-arch/installer
npx @hm-arch/installer install hermes
npx @hm-arch/installer install claude-code
npx @hm-arch/installer install codex
```

Version-pinned installs remain supported when users need reproducible
environments:

```bash
pip install hm-arch==2.0.4
npm install -g @hm-arch/installer@2.0.4
```

## Verification

Release verification before tagging:

```bash
uv run pytest
uv run python examples/release_smoke.py
python scripts/verify_release_versions.py
cd packages/installer && npm test
```

## Compatibility

- Python: 3.10+
- Node.js: 18+
- Supported agents: Codex, Claude Code, Hermes
- Supported standalone npm targets: linux x86_64/aarch64, darwin arm64, windows
  x86_64
