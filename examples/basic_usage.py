"""Basic usage example for the HM-Arch SDK.

Demonstrates offline add/search without any external LLM or API key.
Run with:

    uv run python examples/basic_usage.py
"""

from hm_arch import HMArch, EventType


def main() -> None:
    # Use an ephemeral in-memory database so the example leaves no files.
    memory = HMArch(db_path=":memory:")

    # Add a few memories.
    r1 = memory.add("用户偏好 Python", event_type=EventType.CONVERSATION)
    print(f"Added: memory_id={r1.memory_id[:8]}… layer={r1.layer} "
          f"importance={r1.importance} decay_1d={r1.decay_estimate['1d']:.4f}")

    memory.add("Agent uses SQLite for persistent storage", event_type=EventType.OBSERVATION)
    memory.add("Python is the preferred language for data science", event_type=EventType.CONVERSATION)

    print()

    # Search for a memory using a partial CJK query.
    results = memory.search("用户偏好", top_k=5)
    print(f"Search '用户偏好': {len(results.results)} result(s), "
          f"scanned={results.total_scanned}, timing={results.timing_ms:.2f}ms")
    for item in results.results:
        print(f"  layer=L{item.layer}  score={item.score:.4f}  "
              f"retention={item.retention:.2f}  relevance={item.relevance:.2f}  "
              f"content={item.content!r}")

    print()

    # Search for a memory using an English query.
    results2 = memory.search("Python language preference", top_k=5)
    print(f"Search 'Python language preference': {len(results2.results)} result(s)")
    for item in results2.results:
        print(f"  layer=L{item.layer}  score={item.score:.4f}  content={item.content!r}")

    memory.close()


if __name__ == "__main__":
    main()
