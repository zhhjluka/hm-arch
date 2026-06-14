# HM-Arch v2.0.3

HM-Arch **2.0.3** is a patch release for npm-managed Codex and Claude Code
hook commands on standalone installs.

## Fixes

- Fixed Codex and Claude Code hook commands created by the npm installer when
  the managed runtime is a standalone HM-Arch executable.
- Standalone installs now write hook commands like:

  ```bash
  /path/to/hm-arch claude-code recall
  /path/to/hm-arch codex recall
  ```

  instead of treating the standalone executable like a Python interpreter with
  `-m hm_arch.integrations.cli`.
- `hm-arch status claude-code` and `hm-arch doctor claude-code` no longer warn
  that `hm-arch` is missing from PATH when they are running from the standalone
  executable.
- The same standalone runtime diagnostic improvement applies to Codex hooks.

## Install

```bash
pip install hm-arch==2.0.3
npm install -g @hm-arch/installer@2.0.3
```

For one-shot npm usage:

```bash
npx @hm-arch/installer@2.0.3 install claude-code
npx @hm-arch/installer@2.0.3 install codex
```
