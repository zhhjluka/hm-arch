"""Tests for L4EpisodicLTM episodic long-term archive.

Coverage
--------
* gzip round-trip: decompressed payload is valid JSON with expected fields.
* Month partitioning: ``created_at`` selects ``ltm/YYYY-MM/`` directory.
* Deterministic path from ``memory_id`` and ``created_at``.
* Metadata preservation on archive / retrieve.
* ``list_archives()`` enumerates written files.
* ``purge()`` removes files and returns structured ``PurgeResult``.
* Tests use isolated ``tmp_path`` fixtures (no shared state).
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hm_arch.layers.l4_ltm import (
    ArchiveResult,
    ArchivedEpisodic,
    L4EpisodicLTM,
    PurgeResult,
    _memory_file_hash,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fixed_created() -> datetime:
    return datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def l4(tmp_path: Path) -> L4EpisodicLTM:
    return L4EpisodicLTM(tmp_path)


# ---------------------------------------------------------------------------
# Construction / constants
# ---------------------------------------------------------------------------


def test_layer_index_is_four() -> None:
    assert L4EpisodicLTM.LAYER_INDEX == 4


# ---------------------------------------------------------------------------
# Deterministic paths and month partitioning
# ---------------------------------------------------------------------------


def test_archive_path_is_deterministic(l4: L4EpisodicLTM) -> None:
    mid = "deadbeef" * 4
    created = _fixed_created()
    rel = l4.relative_archive_path(mid, created)
    expected_hash = _memory_file_hash(mid)
    assert rel == f"ltm/2024-06/{expected_hash}.json.gz"


def test_same_memory_id_same_hash_different_calls(l4: L4EpisodicLTM) -> None:
    mid = "consistent-id-001"
    created = _fixed_created()
    p1 = l4.relative_archive_path(mid, created)
    p2 = l4.relative_archive_path(mid, created)
    assert p1 == p2


def test_month_partition_from_created_at(l4: L4EpisodicLTM, tmp_path: Path) -> None:
    mid = "month-partition-test"
    jan = datetime(2025, 1, 10, tzinfo=timezone.utc)
    mar = datetime(2025, 3, 10, tzinfo=timezone.utc)

    l4.archive(
        mid,
        "january episode",
        created_at=jan,
        retention=0.1,
        importance=0.5,
    )
    l4.archive(
        "other-id",
        "march episode",
        created_at=mar,
        retention=0.1,
        importance=0.5,
    )

    assert (tmp_path / "ltm" / "2025-01").is_dir()
    assert (tmp_path / "ltm" / "2025-03").is_dir()
    assert not (tmp_path / "ltm" / "2025-02").exists()


# ---------------------------------------------------------------------------
# gzip round-trip and JSON validity
# ---------------------------------------------------------------------------


def test_gzip_round_trip_valid_json(l4: L4EpisodicLTM, tmp_path: Path) -> None:
    mid = "gzip-round-trip"
    result = l4.archive(
        mid,
        "compressed episodic content",
        created_at=_fixed_created(),
        retention=0.12,
        importance=0.7,
        metadata={"source": "l2", "event_type": "conversation"},
    )

    file_path = tmp_path / result.path
    assert file_path.suffix == ".gz"
    assert file_path.name.endswith(".json.gz")

    with gzip.open(file_path, "rb") as fh:
        payload = json.loads(fh.read().decode("utf-8"))

    assert payload["memory_id"] == mid
    assert payload["content"] == "compressed episodic content"
    assert payload["layer"] == 2
    assert payload["retention"] == pytest.approx(0.12)
    assert payload["importance"] == pytest.approx(0.7)
    assert payload["metadata"] == {"source": "l2", "event_type": "conversation"}
    assert "created_at" in payload
    assert "archived_at" in payload


def test_retrieve_returns_archived_episodic(l4: L4EpisodicLTM) -> None:
    mid = "retrieve-by-id"
    created = _fixed_created()
    updated = datetime(2024, 6, 16, 8, 0, 0, tzinfo=timezone.utc)

    l4.archive(
        mid,
        "low retention memory",
        created_at=created,
        updated_at=updated,
        retention=0.08,
        importance=0.4,
        metadata={"tag": "important"},
    )

    item = l4.retrieve(mid)
    assert item is not None
    assert isinstance(item, ArchivedEpisodic)
    assert item.memory_id == mid
    assert item.content == "low retention memory"
    assert item.layer == 2
    assert item.created_at == created
    assert item.updated_at == updated
    assert item.retention == pytest.approx(0.08)
    assert item.importance == pytest.approx(0.4)
    assert item.metadata == {"tag": "important"}
    assert item.archived_at is not None
    assert item.archived_at.tzinfo is not None


def test_retrieve_missing_returns_none(l4: L4EpisodicLTM) -> None:
    assert l4.retrieve("does-not-exist") is None


# ---------------------------------------------------------------------------
# Metadata preservation
# ---------------------------------------------------------------------------


def test_metadata_preservation(l4: L4EpisodicLTM) -> None:
    meta = {
        "event_type": "code",
        "emotion_score": 0.3,
        "nested": {"a": 1},
    }
    mid = "meta-preserve"
    l4.archive(
        mid,
        "metadata rich",
        retention=0.11,
        importance=0.55,
        metadata=meta,
    )
    item = l4.retrieve(mid)
    assert item is not None
    assert item.metadata == meta


# ---------------------------------------------------------------------------
# list_archives
# ---------------------------------------------------------------------------


def test_list_archives_empty(l4: L4EpisodicLTM) -> None:
    assert l4.list_archives() == []


def test_list_archives_returns_written_files(l4: L4EpisodicLTM) -> None:
    ids = ["list-a", "list-b", "list-c"]
    paths: list[str] = []
    for mid in ids:
        result = l4.archive(mid, f"content-{mid}", retention=0.1, importance=0.5)
        paths.append(result.path)

    listed = l4.list_archives()
    assert len(listed) == 3
    assert {entry.memory_id for entry in listed} == set(ids)
    assert {entry.path for entry in listed} == set(paths)
    for entry in listed:
        assert isinstance(entry, ArchiveResult)
        assert entry.compressed_bytes > 0


# ---------------------------------------------------------------------------
# purge
# ---------------------------------------------------------------------------


def test_purge_removes_file_and_returns_result(l4: L4EpisodicLTM, tmp_path: Path) -> None:
    mid = "purge-me"
    result = l4.archive(mid, "to delete", retention=0.05, importance=0.3)
    file_path = tmp_path / result.path
    assert file_path.is_file()

    purge_result = l4.purge(mid)
    assert isinstance(purge_result, PurgeResult)
    assert purge_result.memory_id == mid
    assert purge_result.removed is True
    assert purge_result.path == result.path
    assert purge_result.error is None
    assert not file_path.exists()
    assert l4.retrieve(mid) is None


def test_purge_missing_returns_not_removed(l4: L4EpisodicLTM) -> None:
    purge_result = l4.purge("never-archived")
    assert purge_result.removed is False
    assert purge_result.path == ""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_archive_rejects_invalid_retention(l4: L4EpisodicLTM) -> None:
    with pytest.raises(ValueError, match="retention"):
        l4.archive("x", "y", retention=1.5, importance=0.5)


def test_archive_rejects_empty_memory_id(l4: L4EpisodicLTM) -> None:
    with pytest.raises(ValueError, match="memory_id"):
        l4.archive("", "content", retention=0.1, importance=0.5)


# ---------------------------------------------------------------------------
# Package import
# ---------------------------------------------------------------------------


def test_importable_from_layers_package() -> None:
    from hm_arch.layers import L4EpisodicLTM as L4FromPkg

    assert L4FromPkg is L4EpisodicLTM
