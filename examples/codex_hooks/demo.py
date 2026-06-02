"""Offline demo for Codex hook handlers (no Codex CLI required).

Run from the repository root::

    uv run python examples/codex_hooks/demo.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hm_arch import EventType, HMArch, MemoryConfig

from examples.agent_hooks_common import (
    build_turn_start_context,
    record_turn_end,
    run_idle_consolidation,
)
from examples.codex_hooks.hooks import (
    codex_idle_consolidation_hook,
    codex_turn_end_hook,
    codex_turn_start_hook,
)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "codex_hooks.db")
        config = MemoryConfig(db_path=db_path, replay_sample_ratio=1.0)

        with HMArch(config=config) as memory:
            memory.add(
                "Project uses pytest and uv for offline verification",
                event_type=EventType.OBSERVATION,
                importance=0.8,
            )
            memory.add(
                "User prefers concise commit messages",
                event_type=EventType.CONVERSATION,
                importance=0.9,
            )

        task = "How do we run offline tests?"
        context = codex_turn_start_hook(
            {"prompt": task},
            db_path=db_path,
        )
        assert "pytest" in context or "offline" in context.lower()
        print(f"Turn-start context ({len(context)} chars):\n{context}\n")

        ids = codex_turn_end_hook(
            {
                "prompt": task,
                "last_assistant_message": "Use uv run pytest for the full suite.",
            },
            db_path=db_path,
        )
        assert len(ids) == 2
        print(f"Turn-end recorded memory ids: {ids}\n")

        summary = codex_idle_consolidation_hook({}, db_path=db_path)
        assert "extracted_semantics" in summary
        print(f"Idle consolidation: {summary}\n")

        with HMArch(config=config) as memory:
            direct_context = build_turn_start_context(memory, task)
            assert direct_context
            record_turn_end(
                memory,
                "What testing command should I use?",
                "Run uv run pytest.",
            )
            report = run_idle_consolidation(memory)
            stats = memory.get_stats()
            assert stats.last_consolidation_at is not None
            print(
                f"Direct API check: consolidation extracted={report.extracted_semantics}, "
                f"L2 count={stats.by_layer[2]}"
            )

    print("Codex hooks demo completed successfully.")


if __name__ == "__main__":
    main()
