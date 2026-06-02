"""Basic usage example for the HM-Arch memory SDK.

Demonstrates the core add/search workflow using an in-process SQLite database
so the example runs offline without any external API keys or network access.

Run with::

    python examples/basic_usage.py
"""

from hm_arch import EventType, HMArch


def main() -> None:
    # Use an in-memory database so the example leaves no files on disk.
    with HMArch(db_path=":memory:") as memory:
        # --- Store some memories ------------------------------------------
        r1 = memory.add(
            "用户偏好 Python",
            event_type=EventType.CONVERSATION,
        )
        print(f"Added memory {r1.memory_id[:8]}… (layer {r1.layer})")

        memory.add(
            "The agent successfully fixed the import error in utils.py",
            event_type=EventType.OBSERVATION,
            importance=0.8,
        )

        memory.add(
            "User prefers concise code reviews with inline comments",
            event_type=EventType.CONVERSATION,
        )

        # --- Search -----------------------------------------------------------
        print("\n--- Search: 用户喜欢什么语言 ---")
        results = memory.search("用户喜欢什么语言", top_k=5)
        print(
            f"Scanned {results.total_scanned} candidates in"
            f" {results.timing_ms:.1f} ms"
        )
        for i, item in enumerate(results.results, 1):
            print(
                f"  {i}. [L{item.layer}] score={item.score:.4f}"
                f" ret={item.retention:.2f} rel={item.relevance:.2f}"
                f"  '{item.content[:60]}'"
            )

        assert results.results, "Expected at least one result"
        assert results.results[0].score >= results.results[-1].score, (
            "Results must be sorted descending by score"
        )

        print("\n--- Search: code review preferences ---")
        results2 = memory.search("code review preferences", top_k=3)
        for i, item in enumerate(results2.results, 1):
            print(
                f"  {i}. [L{item.layer}] score={item.score:.4f}"
                f"  '{item.content[:60]}'"
            )

        print("\n--- Stats ---")
        stats = memory.get_stats()
        print(f"  total={stats.total_memories} by_layer={stats.by_layer}")
        print(f"  storage={stats.storage_size_mb:.4f} MB")

        print("\n--- context() demo ---")
        l1_before = memory._l1.size
        with memory.context():
            memory.add("temporary note during sub-task")
        assert memory._l1.size == l1_before

        print("\nBasic usage example completed successfully.")


if __name__ == "__main__":
    main()
