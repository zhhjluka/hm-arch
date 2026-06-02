"""Release smoke test for HM-Arch.

Exercises the documented public API in-process (in-memory SQLite) so
maintainers can verify a build before tagging or publishing. Intended for
the release checklist — not a substitute for pytest.

Run with::

    python examples/release_smoke.py

Or after editable install::

    python -m pip install -e .
    python examples/release_smoke.py
"""

from __future__ import annotations

import hm_arch
from hm_arch import (
    ConsolidationReport,
    EventType,
    ForgetResult,
    HMArch,
    MemoryConfig,
    MemoryItem,
    MemoryReceipt,
    MemoryStats,
    RetentionCurve,
    SearchResult,
)


def _check_public_exports() -> None:
    expected = {
        "__version__",
        "HMArch",
        "MemoryConfig",
        "EventType",
        "MemoryReceipt",
        "MemoryItem",
        "SearchResult",
        "ConsolidationReport",
        "RetentionCurve",
        "MemoryStats",
        "ForgetResult",
    }
    missing = expected - set(hm_arch.__all__)
    assert not missing, f"Missing from hm_arch.__all__: {missing}"
    print(f"hm_arch {hm_arch.__version__} — public exports OK")


def _check_presets() -> None:
    for name in ("code_agent", "chat_agent", "research_agent"):
        cfg = MemoryConfig.preset(name)
        assert cfg.db_path
    print("MemoryConfig presets OK")


def _check_facade() -> None:
    with HMArch(db_path=":memory:") as memory:
        receipt: MemoryReceipt = memory.add(
            "release smoke test",
            event_type=EventType.SYSTEM,
            importance=0.5,
        )
        assert receipt.memory_id
        assert receipt.layer == 2

        result: SearchResult = memory.search("release smoke", top_k=3)
        assert isinstance(result, SearchResult)
        assert result.total_scanned >= 0
        assert result.timing_ms >= 0
        for item in result.results:
            assert isinstance(item, MemoryItem)

        report: ConsolidationReport = memory.consolidate()
        assert report.duration_seconds >= 0

        curve: RetentionCurve = memory.get_retention_curve(layer=2)
        assert curve.days and len(curve.days) == len(curve.retention)

        stats: MemoryStats = memory.get_stats()
        assert stats.total_memories >= 1
        assert 2 in stats.by_layer

        with memory.context():
            memory.add("ephemeral L1 note", event_type=EventType.TASK)

    assert isinstance(ForgetResult.__doc__, str)
    print("HMArch facade smoke OK")


def main() -> None:
    _check_public_exports()
    _check_presets()
    _check_facade()
    print("Release smoke test passed.")


if __name__ == "__main__":
    main()
