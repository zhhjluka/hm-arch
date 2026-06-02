"""Tests for L5ProceduralMemory.

Coverage
--------
Construction
* Layer index is 5.
* Invalid max_skills raises ValueError.

store_skill()
* Persists a skill by name.
* Returns SkillRecord with expected fields.
* Upsert by name updates description/code without resetting stats.
* Empty name raises ValueError.
* max_skills cap enforced for new names.

match_skill()
* Returns None on empty store.
* Returns None for empty query.
* CJK query matches skill with CJK description (git_push / 推代码).
* Increments usage_count when record_usage=True.
* Sets last_used_at on match.
* record_usage=False leaves usage_count unchanged.
* Deterministic tie-break on equal relevance (name ascending).

list_skills()
* Returns all skills sorted by name.
* Empty list when store is empty.

record_skill_result()
* Success updates success_rate to 1.0 on first record.
* Failure updates success_rate to 0.0 on first record.
* Success then failure yields 0.5 mean.
* Updates average_duration_ms when duration supplied.
* Unknown skill raises ValueError.
* Negative duration_ms raises ValueError.
* Lookup by skill name works.

Persistence
* Skills survive DB close and reopen.
* usage_count and success_rate preserved across reopen.

Importability
* L5ProceduralMemory and SkillRecord importable from hm_arch.layers.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from hm_arch.layers import L5ProceduralMemory, SkillRecord
from hm_arch.storage.sqlite import SQLiteStore


def _make_db(path: str = ":memory:") -> SQLiteStore:
    db = SQLiteStore(path)
    db.connect()
    db.initialize_schema()
    return db


def _make_l5(path: str = ":memory:", max_skills: int | None = None) -> L5ProceduralMemory:
    return L5ProceduralMemory(_make_db(path), max_skills=max_skills)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_layer_index_is_five() -> None:
    assert L5ProceduralMemory.LAYER_INDEX == 5


def test_invalid_max_skills_raises() -> None:
    db = _make_db()
    with pytest.raises(ValueError, match="max_skills"):
        L5ProceduralMemory(db, max_skills=0)


# ---------------------------------------------------------------------------
# store_skill
# ---------------------------------------------------------------------------


def test_store_skill_persists() -> None:
    l5 = _make_l5()
    skill = l5.store_skill(
        "git_push",
        description="Push commits to remote 推代码",
        code="git push origin HEAD",
    )
    assert skill.name == "git_push"
    assert skill.description == "Push commits to remote 推代码"
    assert skill.code == "git push origin HEAD"
    assert skill.usage_count == 0
    assert skill.success_rate is None
    assert l5.count() == 1


def test_store_skill_upsert_preserves_stats() -> None:
    l5 = _make_l5()
    l5.store_skill("git_push", description="v1")
    l5.match_skill("git_push")
    l5.record_skill_result("git_push", True, duration_ms=100.0)

    updated = l5.store_skill("git_push", description="v2", code="git push")
    assert updated.description == "v2"
    assert updated.code == "git push"
    assert updated.usage_count == 1
    assert updated.success_rate == pytest.approx(1.0)
    assert updated.average_duration_ms == pytest.approx(100.0)


def test_store_skill_empty_name_raises() -> None:
    l5 = _make_l5()
    with pytest.raises(ValueError, match="name"):
        l5.store_skill("  ")


def test_max_skills_cap() -> None:
    l5 = _make_l5(max_skills=2)
    l5.store_skill("a")
    l5.store_skill("b")
    with pytest.raises(ValueError, match="max_skills"):
        l5.store_skill("c")


# ---------------------------------------------------------------------------
# match_skill
# ---------------------------------------------------------------------------


def test_match_skill_cjk_query() -> None:
    l5 = _make_l5()
    l5.store_skill(
        "git_push",
        description="Push commits to remote 推代码",
        code="git push",
    )
    l5.store_skill("run_tests", description="Execute pytest suite")

    hit = l5.match_skill("推代码")
    assert hit is not None
    assert hit.name == "git_push"
    assert hit.relevance > 0.0


def test_match_skill_increments_usage_count() -> None:
    l5 = _make_l5()
    l5.store_skill("git_push", description="推代码")
    hit = l5.match_skill("推代码")
    assert hit is not None
    assert hit.usage_count == 1
    hit2 = l5.match_skill("推代码")
    assert hit2 is not None
    assert hit2.usage_count == 2


def test_match_skill_sets_last_used_at() -> None:
    l5 = _make_l5()
    l5.store_skill("git_push", description="推代码")
    hit = l5.match_skill("推代码")
    assert hit is not None
    assert hit.last_used_at is not None


def test_match_skill_no_usage_when_disabled() -> None:
    l5 = _make_l5()
    l5.store_skill("git_push", description="推代码")
    hit = l5.match_skill("推代码", record_usage=False)
    assert hit is not None
    assert hit.usage_count == 0


def test_match_skill_empty_store() -> None:
    l5 = _make_l5()
    assert l5.match_skill("anything") is None


def test_match_skill_empty_query() -> None:
    l5 = _make_l5()
    l5.store_skill("git_push", description="推代码")
    assert l5.match_skill("") is None


def test_match_skill_tie_break_by_name() -> None:
    l5 = _make_l5()
    l5.store_skill("alpha", description="deploy release")
    l5.store_skill("beta", description="deploy release")
    hit = l5.match_skill("deploy release", record_usage=False)
    assert hit is not None
    assert hit.name == "alpha"


# ---------------------------------------------------------------------------
# list_skills
# ---------------------------------------------------------------------------


def test_list_skills_sorted_by_name() -> None:
    l5 = _make_l5()
    l5.store_skill("zebra")
    l5.store_skill("alpha")
    names = [s.name for s in l5.list_skills()]
    assert names == ["alpha", "zebra"]


def test_list_skills_empty() -> None:
    l5 = _make_l5()
    assert l5.list_skills() == []


# ---------------------------------------------------------------------------
# record_skill_result
# ---------------------------------------------------------------------------


def test_record_success_and_failure_updates_rate() -> None:
    l5 = _make_l5()
    l5.store_skill("git_push")
    l5.record_skill_result("git_push", True)
    after_success = l5.get_skill("git_push")
    assert after_success is not None
    assert after_success.success_rate == pytest.approx(1.0)

    l5.record_skill_result("git_push", False)
    after_failure = l5.get_skill("git_push")
    assert after_failure is not None
    assert after_failure.success_rate == pytest.approx(0.5)


def test_record_failure_first() -> None:
    l5 = _make_l5()
    l5.store_skill("git_push")
    l5.record_skill_result("git_push", False)
    skill = l5.get_skill("git_push")
    assert skill is not None
    assert skill.success_rate == pytest.approx(0.0)


def test_record_duration_updates_average() -> None:
    l5 = _make_l5()
    l5.store_skill("git_push")
    l5.record_skill_result("git_push", True, duration_ms=100.0)
    l5.record_skill_result("git_push", True, duration_ms=200.0)
    skill = l5.get_skill("git_push")
    assert skill is not None
    assert skill.average_duration_ms == pytest.approx(150.0)


def test_record_unknown_skill_raises() -> None:
    l5 = _make_l5()
    with pytest.raises(ValueError, match="not found"):
        l5.record_skill_result("missing", True)


def test_record_negative_duration_raises() -> None:
    l5 = _make_l5()
    l5.store_skill("git_push")
    with pytest.raises(ValueError, match="duration_ms"):
        l5.record_skill_result("git_push", True, duration_ms=-1.0)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_skills_persist_across_reopen() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "agent.db")
        l5 = _make_l5(db_path)
        l5.store_skill("git_push", description="推代码", code="git push")
        l5.match_skill("推代码")
        l5.record_skill_result("git_push", True, duration_ms=50.0)

        db = l5._db
        db.close()

        db2 = SQLiteStore(db_path)
        db2.connect()
        db2.initialize_schema()
        l5b = L5ProceduralMemory(db2)

        skill = l5b.get_skill("git_push")
        assert skill is not None
        assert skill.description == "推代码"
        assert skill.code == "git push"
        assert skill.usage_count == 1
        assert skill.success_rate == pytest.approx(1.0)
        assert skill.average_duration_ms == pytest.approx(50.0)

        hit = l5b.match_skill("推代码", record_usage=False)
        assert hit is not None
        assert hit.name == "git_push"
        db2.close()


# ---------------------------------------------------------------------------
# Importability
# ---------------------------------------------------------------------------


def test_importable_from_layers_package() -> None:
    from hm_arch.layers import L5ProceduralMemory as L5
    from hm_arch.layers import SkillRecord as SR

    assert L5 is L5ProceduralMemory
    assert SR is SkillRecord


def test_skill_record_is_dataclass() -> None:
    skill = SkillRecord(
        id="1",
        name="n",
        description=None,
        code=None,
        usage_count=0,
        last_used_at=None,
        success_rate=None,
        average_duration_ms=None,
    )
    assert skill.name == "n"
