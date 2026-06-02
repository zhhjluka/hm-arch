"""Tests for L5ProceduralMemory.

Coverage
--------
store_skill()
* Persists a skill by name and returns a non-empty skill_id.
* Updates description/code on re-store with the same name.
* Rejects empty name.

match_skill()
* Returns the most relevant skill for a CJK query.
* Increments usage_count on each match.
* Sets last_used_at on match.
* Returns None for empty query or zero-overlap query.

list_skills()
* Returns all skills ordered by name.
* Exposes stats prefix stripped from description.

record_skill_result()
* Updates success_rate from success/failure outcomes.
* Updates average_duration_ms as a running mean.
* Does not increment usage_count.
* Returns None for unknown skill.
* Rejects negative duration_ms.

Persistence
* Skills and statistics survive DB close/reopen.

Importability
* L5ProceduralMemory and ProceduralSkill importable from hm_arch.layers.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from hm_arch.layers import L5ProceduralMemory, ProceduralSkill
from hm_arch.storage.sqlite import SQLiteStore


def _make_db(path: str = ":memory:") -> SQLiteStore:
    db = SQLiteStore(path)
    db.connect()
    db.initialize_schema()
    return db


# ---------------------------------------------------------------------------
# store_skill
# ---------------------------------------------------------------------------


def test_store_skill_persists() -> None:
    db = _make_db()
    l5 = L5ProceduralMemory(db)
    skill_id = l5.store_skill(
        "git_push",
        description="推代码到远程仓库",
        code="git push origin HEAD",
    )
    assert skill_id
    row = db.query("SELECT * FROM skills WHERE name = ?", ("git_push",))[0]
    assert row["id"] == skill_id
    assert row["description"] == "推代码到远程仓库"
    assert row["code"] == "git push origin HEAD"
    assert row["usage_count"] == 0


def test_store_skill_updates_existing_name() -> None:
    db = _make_db()
    l5 = L5ProceduralMemory(db)
    first_id = l5.store_skill("git_push", description="old")
    second_id = l5.store_skill("git_push", description="推代码到远程", code="git push")
    assert second_id == first_id
    skill = l5.get_skill("git_push")
    assert skill is not None
    assert skill.description == "推代码到远程"
    assert skill.code == "git push"


def test_store_skill_rejects_empty_name() -> None:
    db = _make_db()
    l5 = L5ProceduralMemory(db)
    with pytest.raises(ValueError, match="name must be non-empty"):
        l5.store_skill("   ")


# ---------------------------------------------------------------------------
# match_skill
# ---------------------------------------------------------------------------


def test_match_skill_cjk_query() -> None:
    db = _make_db()
    l5 = L5ProceduralMemory(db)
    l5.store_skill("git_push", description="推代码到远程仓库")
    l5.store_skill("run_tests", description="运行单元测试")

    hit = l5.match_skill("推代码")
    assert hit is not None
    assert hit.name == "git_push"
    assert hit.relevance > 0.0


def test_match_skill_increments_usage_count() -> None:
    db = _make_db()
    l5 = L5ProceduralMemory(db)
    l5.store_skill("git_push", description="推代码")
    l5.match_skill("推代码")
    l5.match_skill("推代码")
    skill = l5.get_skill("git_push")
    assert skill is not None
    assert skill.usage_count == 2


def test_match_skill_sets_last_used_at() -> None:
    db = _make_db()
    l5 = L5ProceduralMemory(db)
    l5.store_skill("git_push", description="推代码")
    hit = l5.match_skill("推代码")
    assert hit is not None
    assert hit.last_used_at is not None


def test_match_skill_returns_none_for_no_overlap() -> None:
    db = _make_db()
    l5 = L5ProceduralMemory(db)
    l5.store_skill("git_push", description="推代码")
    assert l5.match_skill("完全无关的查询") is None


def test_match_skill_returns_none_for_empty_query() -> None:
    db = _make_db()
    l5 = L5ProceduralMemory(db)
    l5.store_skill("git_push", description="推代码")
    assert l5.match_skill("") is None


# ---------------------------------------------------------------------------
# list_skills
# ---------------------------------------------------------------------------


def test_list_skills_ordered_by_name() -> None:
    db = _make_db()
    l5 = L5ProceduralMemory(db)
    l5.store_skill("zebra")
    l5.store_skill("alpha")
    names = [s.name for s in l5.list_skills()]
    assert names == ["alpha", "zebra"]


# ---------------------------------------------------------------------------
# record_skill_result
# ---------------------------------------------------------------------------


def test_record_skill_result_updates_success_rate() -> None:
    db = _make_db()
    l5 = L5ProceduralMemory(db)
    l5.store_skill("git_push", description="推代码")
    l5.record_skill_result("git_push", success=True, duration_ms=100.0)
    after_success = l5.get_skill("git_push")
    assert after_success is not None
    assert after_success.success_rate == pytest.approx(1.0)

    l5.record_skill_result("git_push", success=False, duration_ms=200.0)
    after_failure = l5.get_skill("git_push")
    assert after_failure is not None
    assert after_failure.success_rate == pytest.approx(0.5)


def test_record_skill_result_updates_average_duration() -> None:
    db = _make_db()
    l5 = L5ProceduralMemory(db)
    l5.store_skill("git_push")
    l5.record_skill_result("git_push", success=True, duration_ms=100.0)
    l5.record_skill_result("git_push", success=True, duration_ms=300.0)
    skill = l5.get_skill("git_push")
    assert skill is not None
    assert skill.average_duration_ms == pytest.approx(200.0)


def test_record_skill_result_does_not_increment_usage_count() -> None:
    db = _make_db()
    l5 = L5ProceduralMemory(db)
    l5.store_skill("git_push")
    l5.record_skill_result("git_push", success=True, duration_ms=50.0)
    skill = l5.get_skill("git_push")
    assert skill is not None
    assert skill.usage_count == 0


def test_record_skill_result_unknown_skill() -> None:
    db = _make_db()
    l5 = L5ProceduralMemory(db)
    assert l5.record_skill_result("missing", success=True, duration_ms=1.0) is None


def test_record_skill_result_rejects_negative_duration() -> None:
    db = _make_db()
    l5 = L5ProceduralMemory(db)
    l5.store_skill("git_push")
    with pytest.raises(ValueError, match="duration_ms must be non-negative"):
        l5.record_skill_result("git_push", success=True, duration_ms=-1.0)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_skills_persist_across_db_reopen() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "agent.db"
        db = _make_db(str(db_path))
        l5 = L5ProceduralMemory(db)
        l5.store_skill("git_push", description="推代码", code="git push")
        l5.match_skill("推代码")
        l5.record_skill_result("git_push", success=True, duration_ms=120.0)
        db.close()

        db2 = _make_db(str(db_path))
        l5b = L5ProceduralMemory(db2)
        skill = l5b.get_skill("git_push")
        assert skill is not None
        assert skill.description == "推代码"
        assert skill.code == "git push"
        assert skill.usage_count == 1
        assert skill.success_rate == pytest.approx(1.0)
        assert skill.average_duration_ms == pytest.approx(120.0)

        hit = l5b.match_skill("推代码")
        assert hit is not None
        assert hit.name == "git_push"
        assert l5b.get_skill("git_push").usage_count == 2


# ---------------------------------------------------------------------------
# Importability / types
# ---------------------------------------------------------------------------


def test_l5_importable_from_layers_package() -> None:
    assert L5ProceduralMemory is not None
    assert ProceduralSkill is not None


def test_procedural_skill_fields() -> None:
    db = _make_db()
    l5 = L5ProceduralMemory(db)
    l5.store_skill("git_push", description="推代码", code="git push")
    skill = l5.get_skill("git_push")
    assert skill is not None
    assert isinstance(skill.skill_id, str)
    assert skill.name == "git_push"
    assert skill.description == "推代码"
    assert skill.code == "git push"
    assert skill.usage_count == 0
    assert skill.last_used_at is None
    assert skill.success_rate is None
    assert skill.average_duration_ms is None
