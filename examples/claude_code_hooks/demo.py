"""Offline demo for Claude Code hook handlers.

Run from the repository root::

    uv run python examples/claude_code_hooks/demo.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hm_arch import EventType, HMArch, MemoryConfig

from examples.claude_code_hooks.hooks import (
    claude_idle_consolidation_hook,
    claude_turn_end_hook,
    claude_turn_start_hook,
)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "claude_hooks.db")
        config = MemoryConfig(db_path=db_path, replay_sample_ratio=1.0)

        with HMArch(config=config) as memory:
            memory.add(
                "Service layer lives under src/hm_arch/",
                event_type=EventType.OBSERVATION,
            )
            memory.add(
                "User wants hook examples to stay offline",
                event_type=EventType.CONVERSATION,
                importance=0.85,
            )

        task = "Where is the SDK source and what constraints apply?"
        context = claude_turn_start_hook({"prompt": task}, db_path=db_path)
        assert "src/hm_arch" in context or "offline" in context.lower()
        print(f"Turn-start context ({len(context)} chars):\n{context}\n")

        ids = claude_turn_end_hook(
            {
                "prompt": task,
                "last_assistant_message": "Keep examples under examples/ and run pytest offline.",
            },
            db_path=db_path,
        )
        assert len(ids) == 2
        print(f"Turn-end recorded memory ids: {ids}\n")

        summary = claude_idle_consolidation_hook(
            {"hook_event_name": "TeammateIdle"},
            db_path=db_path,
        )
        assert summary["extracted_semantics"] >= 0
        print(f"Idle consolidation: {summary}\n")

        with HMArch(config=config) as memory:
            stats = memory.get_stats()
            assert stats.by_layer[2] >= 4
            assert stats.last_consolidation_at is not None

    print("Claude Code hooks demo completed successfully.")


if __name__ == "__main__":
    main()
