"""Tests for HM-26 public API contract completion."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hm_arch import AgentContext, ForgetResult, HMArch, MemoryConfig
from hm_arch.consolidation import ConsolidationEngine


@pytest.fixture()
def mem() -> HMArch:
    instance = HMArch(db_path=":memory:")
    yield instance
    instance.close()


def test_forget_removes_memory_from_default_search(mem: HMArch) -> None:
    receipt = mem.add("secret forgotten probe", importance=0.5)
    mem.forget(receipt.memory_id, force=True)
    result = mem.search("secret forgotten probe", min_retention=0.0)
    assert not any(
        "secret forgotten probe" in item.content for item in result.results
    )


def test_context_prd_load_save_pattern(mem: HMArch) -> None:
    mem.add("persisted baseline")
    with mem.context() as ctx:
        assert hasattr(ctx, "load_session")
        assert hasattr(ctx, "save_session")
        ctx.load_session()
        mem.add("scoped note")
        ctx.save_session()
    assert mem._l1.size >= 1


def test_get_retention_curve_positional_memory_id(mem: HMArch) -> None:
    receipt = mem.add("positional curve probe")
    curve = mem.get_retention_curve(receipt.memory_id, days_ahead=90)
    assert 90 in curve.days
    assert len(curve.days) == len(curve.retention)


def test_get_retention_curve_positional_days_ahead(mem: HMArch) -> None:
    receipt = mem.add("curve horizon probe")
    curve = mem.get_retention_curve(receipt.memory_id, 30)
    assert max(curve.days) <= 30


def test_forget_single_memory_marks_deleted(mem: HMArch) -> None:
    receipt = mem.add("ephemeral fact", importance=0.2)
    mem._db.execute(
        "UPDATE memory_index SET current_retention = 0.01 WHERE id = ?",
        (receipt.memory_id,),
    )
    result = mem.forget(receipt.memory_id)
    assert isinstance(result, ForgetResult)
    assert result.forgotten_count + result.archived_count >= 1
    rows = mem._db.query(
        "SELECT status FROM memory_index WHERE id = ?",
        (receipt.memory_id,),
    )
    assert rows[0]["status"] in ("deleted", "archived")


def test_forget_single_skips_high_retention_without_force(mem: HMArch) -> None:
    receipt = mem.add("important fact", importance=0.9)
    result = mem.forget(receipt.memory_id, force=False)
    assert result.forgotten_count == 0
    assert result.archived_count == 0


def test_forget_single_force_deletes_high_retention(mem: HMArch) -> None:
    receipt = mem.add("important fact", importance=0.9)
    result = mem.forget(receipt.memory_id, force=True)
    assert result.forgotten_count >= 1


def test_forget_global_scan_processes_deletable(mem: HMArch) -> None:
    receipt = mem.add("stale fact", importance=0.3)
    mem._db.execute(
        """
        UPDATE memory_index
           SET current_retention = 0.01, status = 'deletable'
         WHERE id = ?
        """,
        (receipt.memory_id,),
    )
    result = mem.forget()
    assert result.forgotten_count >= 1
    assert any(d["memory_id"] == receipt.memory_id for d in result.details)


def test_search_default_min_retention_is_prd(mem: HMArch) -> None:
    import inspect

    sig = inspect.signature(HMArch.search)
    assert sig.parameters["min_retention"].default == pytest.approx(0.1)
    assert sig.parameters["top_k"].default == 10


def test_add_default_event_type_is_conversation(mem: HMArch) -> None:
    import inspect
    from hm_arch import EventType

    sig = inspect.signature(HMArch.add)
    assert sig.parameters["event_type"].default is EventType.CONVERSATION


def test_search_min_retention_filters_low_retention(mem: HMArch) -> None:
    mem.add("high retention topic alpha")
    receipt = mem.add("low retention topic beta")
    mem._db.execute(
        "UPDATE memory_index SET current_retention = 0.1 WHERE id = ?",
        (receipt.memory_id,),
    )
    unfiltered = mem.search("topic", top_k=10, min_retention=0.0)
    filtered = mem.search("topic", top_k=10, min_retention=0.5)
    assert len(unfiltered.results) >= len(filtered.results)
    for item in filtered.results:
        assert item.retention >= 0.5


def test_search_layer_filter_excludes_layers(mem: HMArch) -> None:
    mem.add("layer filter probe text")
    only_l2 = mem.search("probe", top_k=5, layer_filter=[2])
    for item in only_l2.results:
        assert item.layer == 2
    assert only_l2.source_breakdown.get(1, 0) == 0


def test_get_retention_curve_for_memory_id(mem: HMArch) -> None:
    receipt = mem.add("curve probe")
    mem._db.execute(
        "UPDATE memory_index SET initial_strength = 0.5 WHERE id = ?",
        (receipt.memory_id,),
    )
    curve = mem.get_retention_curve(memory_id=receipt.memory_id)
    default = mem.get_retention_curve(layer=2)
    day_idx = curve.days.index(30)
    assert curve.retention[day_idx] < default.retention[day_idx]


def test_get_retention_curve_unknown_memory_raises(mem: HMArch) -> None:
    with pytest.raises(ValueError, match="not found"):
        mem.get_retention_curve(memory_id="does-not-exist")


def test_agent_context_save_and_load_session() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "ctx.db")
        m1 = HMArch(db_path=db_path)
        m1.add("session baseline")
        ctx = AgentContext(m1)
        ctx.save_session()
        m1.add("should not persist in saved snapshot alone")
        m1.close()

        m2 = HMArch(db_path=db_path)
        ctx2 = AgentContext(m2)
        assert ctx2.load_session() is True
        contents = [item.content for item in m2._l1.snapshot()]
        assert any("session baseline" in c for c in contents)
        assert not any("should not persist" in c for c in contents)
        m2.close()


def test_agent_context_manager_restores_l1(mem: HMArch) -> None:
    mem.add("keep")
    size_before = mem._l1.size
    with AgentContext(mem):
        mem.add("discard")
    assert mem._l1.size == size_before


def test_forget_archives_low_retention_l2(tmp_path: Path) -> None:
    cfg = MemoryConfig(
        db_path=str(tmp_path / "f.db"),
        archive_root=str(tmp_path / "arch"),
    )
    mem = HMArch(config=cfg)
    try:
        receipt = mem.add("archive me please", importance=0.4)
        mem._db.execute(
            "UPDATE memory_index SET current_retention = 0.04 WHERE id = ?",
            (receipt.memory_id,),
        )
        result = mem.forget(receipt.memory_id)
        assert result.archived_count >= 1 or result.forgotten_count >= 1
    finally:
        mem.close()
