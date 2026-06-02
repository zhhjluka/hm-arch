"""Coding-agent integration example for the HM-Arch memory SDK.

Shows how an agent loop can persist observations, query memory for context,
use :meth:`~hm_arch.core.HMArch.context` for isolated sub-tasks, and inspect
:meth:`~hm_arch.core.HMArch.get_stats` — all offline with a local SQLite file.

Run with::

    python examples/agent_integration.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hm_arch import EventType, HMArch


def agent_turn(memory: HMArch, observation: str) -> None:
    """Simulate one agent turn: store observation and recall related context."""
    memory.add(observation, event_type=EventType.OBSERVATION)
    hits = memory.search(observation.split()[0] if observation else "", top_k=3)
    print(f"  stored: {observation[:50]}…")
    if hits.results:
        print(f"  recall: {hits.results[0].content[:50]}… (score={hits.results[0].score:.3f})")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / ".agent_memory.db")
        memory = HMArch(db_path=db_path)

        print("=== Agent session ===")
        memory.add(
            "Project uses Python 3.12 and pytest for tests",
            event_type=EventType.CODE,
        )
        agent_turn(memory, "Fixed failing test in test_core.py")
        agent_turn(memory, "User asked for concise PR descriptions")

        print("\n=== Sub-task with context() (L1 isolated) ===")
        session_before = memory._l1.size
        with memory.context():
            memory.add("Scratch: try approach A for the refactor", event_type=EventType.TASK)
            assert memory._l1.size == session_before + 1
        assert memory._l1.size == session_before

        print("\n=== Memory stats ===")
        stats = memory.get_stats()
        print(f"  total memories: {stats.total_memories}")
        print(f"  by layer: {stats.by_layer}")
        print(f"  storage: {stats.storage_size_mb:.4f} MB")
        print(f"  review queue: {stats.review_queue_length}")

        memory.close()

    print("\nAgent integration example completed successfully.")


if __name__ == "__main__":
    main()
