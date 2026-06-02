"""Agent integration example for the HM-Arch memory SDK.

Shows how a coding agent can scope ephemeral working-memory updates with
:meth:`~hm_arch.core.HMArch.context` while persisting durable episodic facts,
and how to inspect store health with :meth:`~hm_arch.core.HMArch.get_stats`.

Runs fully offline (no API keys). Use a temporary on-disk database so stats
include a non-zero storage size.

Run with::

    python examples/agent_integration.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hm_arch import EventType, HMArch, MemoryConfig


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "agent_memory.db")
        config = MemoryConfig(db_path=db_path, replay_sample_ratio=1.0)

        with HMArch(config=config) as memory:
            # --- Baseline session context ---------------------------------
            memory.add(
                "Project uses Python 3.12 and pytest for tests",
                event_type=EventType.OBSERVATION,
            )

            stats0 = memory.get_stats()
            print(f"Initial stats: {stats0.total_memories} memories, "
                  f"L2={stats0.by_layer[2]}, storage={stats0.storage_size_mb:.4f} MB")

            # --- Scoped sub-task: L1 changes roll back on exit ----------
            l1_before_context = memory._l1.size
            with memory.context():
                memory.add(
                    "Scratch: try importing hm_arch from src layout",
                    event_type=EventType.TASK,
                )
                assert memory._l1.size == l1_before_context + 1

            # L1 restored to pre-block snapshot
            assert memory._l1.size == l1_before_context

            # --- Durable episodic memory still accumulates ---------------
            memory.add(
                "User prefers concise pull request descriptions",
                event_type=EventType.CONVERSATION,
                importance=0.9,
            )

            # --- Offline consolidation (optional enrichment) -------------
            report = memory.consolidate()
            print(
                f"Consolidation: extracted={report.extracted_semantics}, "
                f"reviews_scheduled={report.scheduled_reviews}"
            )

            stats1 = memory.get_stats()
            print(
                f"Final stats: total={stats1.total_memories}, "
                f"by_layer={stats1.by_layer}, "
                f"review_queue={stats1.review_queue_length}, "
                f"last_consolidation={stats1.last_consolidation_at is not None}"
            )
            assert stats1.by_layer[2] >= 2
            assert stats1.last_consolidation_at is not None

            results = memory.search("Python pytest", top_k=3)
            assert results.results, "Expected searchable project context"

    print("\nAgent integration example completed successfully.")


if __name__ == "__main__":
    main()
