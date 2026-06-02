"""Tests for HMArch.context() session save/restore (HM-11)."""

from __future__ import annotations

import pytest

from hm_arch import HMArch, EventType


@pytest.fixture()
def mem() -> HMArch:
    instance = HMArch(db_path=":memory:")
    yield instance
    instance.close()


def test_context_restores_l1_after_block(mem: HMArch) -> None:
    mem.add("parent session item")
    before = [item.content for item in mem._l1.snapshot()]

    with mem.context():
        mem.add("temporary sub-task note")
        assert mem._l1.size == len(before) + 1

    after = [item.content for item in mem._l1.snapshot()]
    assert after == before


def test_context_preserves_l2_across_block(mem: HMArch) -> None:
    receipt = mem.add("durable episodic memory")
    with mem.context():
        mem.add("ephemeral working note only in session")
    assert mem._l2.count() == 2
    results = mem.search("durable episodic", top_k=5)
    assert any(r.memory_id == receipt.memory_id for r in results.results)


def test_context_nested_blocks(mem: HMArch) -> None:
    mem.add("outer")
    outer_snapshot = len(mem._l1.snapshot())

    with mem.context():
        mem.add("middle")
        with mem.context():
            mem.add("inner")
            assert mem._l1.size == outer_snapshot + 2
        assert mem._l1.size == outer_snapshot + 1

    assert mem._l1.size == outer_snapshot


def test_context_restores_on_exception(mem: HMArch) -> None:
    mem.add("stable")
    before = mem._l1.size
    with pytest.raises(RuntimeError):
        with mem.context():
            mem.add("will be rolled back from L1")
            raise RuntimeError("sub-task failed")
    assert mem._l1.size == before


def test_context_memory_ids_preserved(mem: HMArch) -> None:
    mem.add("keep this id", event_type=EventType.OBSERVATION)
    ids_before = [item.memory_id for item in mem._l1.snapshot()]
    with mem.context():
        mem.add("discard from L1")
    ids_after = [item.memory_id for item in mem._l1.snapshot()]
    assert ids_after == ids_before
