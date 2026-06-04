# Claude Code hook examples (HM-Arch)

Portable, offline examples for [Claude Code hooks](https://code.claude.com/docs/en/hooks). Hook logic lives in the installed package at ``hm_arch.integrations.claude_code``; the scripts here are thin entrypoints that call the packaged adapter. These scripts do **not** edit your global or project settings automatically.

## Scripts

| Script | Role | Suggested Claude Code event |
|--------|------|-----------------------------|
| `turn_start.py` | Search memory and inject context | `UserPromptSubmit` |
| `turn_end.py` | Record user + assistant messages | `Stop` |
| `idle_consolidate.py` | Run `memory.consolidate()` | `TeammateIdle` |

## Database path

Set `HM_ARCH_DB_PATH` to a SQLite file, or omit it to use `./.hm_arch_agent_memory.db` in the current working directory.

## Example `.claude/settings.json` fragment

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "uv run python examples/claude_code_hooks/turn_start.py",
            "timeout": 15,
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
            "command": "uv run python examples/claude_code_hooks/turn_end.py",
            "timeout": 15
          }
        ]
      }
    ],
    "TeammateIdle": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "uv run python examples/claude_code_hooks/idle_consolidate.py",
            "timeout": 120,
            "statusMessage": "HM-Arch consolidation"
          }
        ]
      }
    ]
  }
}
```

## Offline demo

```bash
uv run python examples/claude_code_hooks/demo.py
```
