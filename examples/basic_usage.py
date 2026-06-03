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

        # --- Consolidation (offline semantic extraction) --------------------
        report = memory.consolidate()
        print(
            f"\n--- Consolidation: extracted={report.extracted_semantics}, "
            f"reviews_scheduled={report.scheduled_reviews}"
        )

        curve = memory.get_retention_curve(layer=2)
        day30_idx = curve.days.index(30) if 30 in curve.days else -1
        if day30_idx >= 0:
            print(
                f"L2 30-day predicted retention: {curve.retention[day30_idx]:.2f}"
            )

        mem_curve = memory.get_retention_curve(memory_id=r1.memory_id)
        print(
            f"Per-memory curve (30d): {mem_curve.retention[mem_curve.days.index(30)]:.2f}"
            if 30 in mem_curve.days
            else "Per-memory curve computed"
        )

        filtered = memory.search(
            "用户",
            top_k=5,
            min_retention=0.0,
            layer_filter=[1, 2, 3],
        )
        print(f"Layer-filtered search hits: {len(filtered.results)}")

        print("\nBasic usage example completed successfully.")


if __name__ == "__main__":
    main()
