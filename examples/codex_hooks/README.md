# Codex hook examples (HM-Arch)

Portable, offline examples for wiring [Codex hooks](https://developers.openai.com/codex/hooks) to HM-Arch memory. These scripts do **not** modify your Codex installation automatically.

## Scripts

| Script | Role | Suggested Codex event |
|--------|------|------------------------|
| `turn_start.py` | Search memory and inject context | `UserPromptSubmit` |
| `turn_end.py` | Record user + assistant messages | `Stop` |
| `idle_consolidate.py` | Run `memory.consolidate()` | idle wrapper / long `Stop` timeout |

## Database path

Set `HM_ARCH_DB_PATH` to a SQLite file, or omit it to use `./.hm_arch_agent_memory.db` in the current working directory (never a hardcoded home path).

## Example `.codex/hooks.json` fragment

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "uv run python examples/codex_hooks/turn_start.py",
            "timeoutSec": 15,
            "statusMessage": "Loading HM-Arch context"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "uv run python examples/codex_hooks/turn_end.py",
            "timeoutSec": 15
          },
          {
            "type": "command",
            "command": "uv run python examples/codex_hooks/idle_consolidate.py",
            "timeoutSec": 120,
            "statusMessage": "HM-Arch consolidation"
          }
        ]
      }
    ]
  }
}
```

Enable hooks in `.codex/config.toml`:

```toml
[features]
hooks = true
```

## Offline demo

```bash
uv run python examples/codex_hooks/demo.py
```
