"""L4 Episodic Long-Term Memory — compressed gzip archive for low-retention L2.

L4 is the durable episodic archive for episodic memories that have fallen below
the L2 retention threshold.  Each archived record is stored as a single
gzip-compressed JSON file:

    ``ltm/YYYY-MM/{sha256(memory_id)}.json.gz``

The month partition is derived from the memory's original ``created_at``
timestamp.  The filename hash is deterministic from ``memory_id``, so
:meth:`retrieve` and :meth:`purge` can locate a file without a separate index.

Design notes
------------
* L4 is **filesystem-backed**; it does not write to SQLite (that wiring arrives
  in HM-19).
* No search or consolidation integration in this milestone — only archive I/O.
* Thread-safety is not guaranteed; callers must synchronise if needed.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


__all__ = [
    "ArchivedEpisodic",
    "ArchiveResult",
    "PurgeResult",
    "L4EpisodicLTM",
]


# ---------------------------------------------------------------------------
# Return types
# ---------------------------------------------------------------------------


@dataclass
class ArchivedEpisodic:
    """A single episodic memory restored from the L4 gzip archive.

    Attributes
    ----------
    memory_id:
        Original unique identifier from the source layer (typically L2).
    content:
        Raw text content of the episode.
    layer:
        Original layer index at archive time (typically ``2``).
    created_at:
        Original creation timestamp (timezone-aware UTC).
    updated_at:
        Last update timestamp from the source index, if known.
    retention:
        Retention value in ``[0, 1]`` at archive time.
    importance:
        Importance score in ``[0, 1]`` at archive time.
    metadata:
        Arbitrary caller-supplied key/value pairs preserved from the source.
    archived_at:
        Timezone-aware UTC timestamp when the record was written to L4.
    """

    memory_id: str
    content: str
    layer: int
    created_at: datetime
    updated_at: datetime | None
    retention: float
    importance: float
    metadata: dict = field(default_factory=dict)
    archived_at: datetime | None = None


@dataclass
class ArchiveResult:
    """Outcome of :meth:`L4EpisodicLTM.archive`.

    Attributes
    ----------
    memory_id:
        The archived memory identifier.
    path:
        Relative path under the L4 root, e.g.
        ``ltm/2024-06/abc123….json.gz``.
    compressed_bytes:
        Size of the written ``.json.gz`` file in bytes.
    """

    memory_id: str
    path: str
    compressed_bytes: int


@dataclass
class PurgeResult:
    """Outcome of :meth:`L4EpisodicLTM.purge`.

    Attributes
    ----------
    memory_id:
        The memory identifier that was requested for purge.
    path:
        Relative path of the removed file, or ``""`` when nothing was found.
    removed:
        ``True`` when a file was deleted from disk.
    error:
        Optional error message when removal failed.
    """

    memory_id: str
    path: str
    removed: bool
    error: str | None = None


# ---------------------------------------------------------------------------
# L4 implementation
# ---------------------------------------------------------------------------


class L4EpisodicLTM:
    """Filesystem-backed episodic long-term archive (layer 4).

    Parameters
    ----------
    root:
        Base directory under which the ``ltm/`` tree is created.  The caller
        is responsible for ensuring the directory exists or is creatable.

    Examples
    --------
    ::

        from pathlib import Path
        from hm_arch.layers.l4_ltm import L4EpisodicLTM

        l4 = L4EpisodicLTM(Path("./agent_data"))
        result = l4.archive(
            memory_id="abc",
            content="User prefers Python",
            retention=0.12,
            importance=0.6,
        )
        item = l4.retrieve("abc")
        assert item is not None
        assert item.content == "User prefers Python"
    """

    LAYER_INDEX: int = 4
    _LTM_DIR: str = "ltm"

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    # ------------------------------------------------------------------
    # Primary public interface
    # ------------------------------------------------------------------

    def archive(
        self,
        memory_id: str,
        content: str,
        *,
        layer: int = 2,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        retention: float,
        importance: float,
        metadata: dict | None = None,
    ) -> ArchiveResult:
        """Write a compressed episodic record to the L4 archive.

        Parameters
        ----------
        memory_id:
            Original memory identifier (typically from L2).
        content:
            Raw episode text.
        layer:
            Source layer index preserved in the payload (default ``2``).
        created_at:
            Original creation time; defaults to current UTC when omitted.
        updated_at:
            Optional last-update timestamp from the source index.
        retention:
            Retention at archive time; must be in ``[0, 1]``.
        importance:
            Importance at archive time; must be in ``[0, 1]``.
        metadata:
            Arbitrary key/value pairs to preserve in the JSON payload.

        Returns
        -------
        ArchiveResult
            Describes the written file path and compressed size.
        """
        if not memory_id:
            raise ValueError("memory_id must be non-empty")
        _validate_unit_interval("retention", retention)
        _validate_unit_interval("importance", importance)

        created = _ensure_utc(created_at or _now())
        updated = _ensure_utc(updated_at) if updated_at is not None else None
        archived_at = _now()
        meta = dict(metadata) if metadata is not None else {}

        payload: dict[str, Any] = {
            "memory_id": memory_id,
            "content": content,
            "layer": layer,
            "created_at": _iso(created),
            "updated_at": _iso(updated) if updated is not None else None,
            "retention": retention,
            "importance": importance,
            "metadata": meta,
            "archived_at": _iso(archived_at),
        }

        dest = self._archive_path(memory_id, created)
        dest.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        with gzip.open(dest, "wb") as fh:
            fh.write(raw)

        rel = _relative_path(self._root, dest)
        return ArchiveResult(
            memory_id=memory_id,
            path=rel,
            compressed_bytes=dest.stat().st_size,
        )

    def retrieve(self, memory_id: str) -> ArchivedEpisodic | None:
        """Load an archived episodic record by ``memory_id``.

        Locates files via the deterministic filename hash.  When more than one
        file exists (e.g. re-archived under a different month partition), the
        record with the latest ``archived_at`` timestamp is returned.

        Parameters
        ----------
        memory_id:
            Original memory identifier.

        Returns
        -------
        ArchivedEpisodic or None
            The restored record, or ``None`` when no archive file exists.
        """
        if not memory_id:
            raise ValueError("memory_id must be non-empty")

        matches = self._find_archive_files(memory_id)
        if not matches:
            return None

        records = [_read_archive_file(path) for path in matches]
        records.sort(key=lambda r: r.archived_at or datetime.min.replace(tzinfo=timezone.utc))
        return records[-1]

    def list_archives(self) -> list[ArchiveResult]:
        """Return metadata for every ``.json.gz`` file under ``ltm/``.

        Results are sorted by relative path for stable ordering.
        """
        ltm_root = self._ltm_root()
        if not ltm_root.is_dir():
            return []

        entries: list[ArchiveResult] = []
        for path in sorted(ltm_root.rglob("*.json.gz")):
            record = _read_archive_file(path)
            entries.append(
                ArchiveResult(
                    memory_id=record.memory_id,
                    path=_relative_path(self._root, path),
                    compressed_bytes=path.stat().st_size,
                )
            )
        return entries

    def purge(self, memory_id: str) -> PurgeResult:
        """Remove all on-disk archive files for ``memory_id``.

        When multiple month partitions contain the same hash filename, every
        matching file is deleted.

        Parameters
        ----------
        memory_id:
            Original memory identifier.

        Returns
        -------
        PurgeResult
            Structured outcome including whether any file was removed.
        """
        if not memory_id:
            raise ValueError("memory_id must be non-empty")

        matches = self._find_archive_files(memory_id)
        if not matches:
            return PurgeResult(memory_id=memory_id, path="", removed=False)

        removed_any = False
        last_path = ""
        last_error: str | None = None

        for path in matches:
            rel = _relative_path(self._root, path)
            try:
                path.unlink()
                removed_any = True
                last_path = rel
            except OSError as exc:
                last_error = str(exc)
                last_path = rel

        return PurgeResult(
            memory_id=memory_id,
            path=last_path,
            removed=removed_any,
            error=last_error,
        )

    # ------------------------------------------------------------------
    # Path helpers (public for deterministic-path tests)
    # ------------------------------------------------------------------

    def archive_path(self, memory_id: str, created_at: datetime) -> Path:
        """Return the absolute path where an archive file would be written."""
        return self._archive_path(memory_id, _ensure_utc(created_at))

    def relative_archive_path(self, memory_id: str, created_at: datetime) -> str:
        """Return the relative ``ltm/YYYY-MM/{hash}.json.gz`` path."""
        return _relative_path(self._root, self.archive_path(memory_id, created_at))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ltm_root(self) -> Path:
        return self._root / self._LTM_DIR

    def _archive_path(self, memory_id: str, created_at: datetime) -> Path:
        month = created_at.strftime("%Y-%m")
        file_hash = _memory_file_hash(memory_id)
        return self._ltm_root() / month / f"{file_hash}.json.gz"

    def _find_archive_files(self, memory_id: str) -> list[Path]:
        ltm_root = self._ltm_root()
        if not ltm_root.is_dir():
            return []
        file_hash = _memory_file_hash(memory_id)
        return sorted(ltm_root.glob(f"**/{file_hash}.json.gz"))


# ---------------------------------------------------------------------------
# Module-level utilities
# ---------------------------------------------------------------------------


def _memory_file_hash(memory_id: str) -> str:
    """Deterministic filename stem from ``memory_id``."""
    return hashlib.sha256(memory_id.encode("utf-8")).hexdigest()


def _read_archive_file(path: Path) -> ArchivedEpisodic:
    with gzip.open(path, "rb") as fh:
        payload = json.loads(fh.read().decode("utf-8"))
    return _payload_to_record(payload)


def _payload_to_record(payload: dict[str, Any]) -> ArchivedEpisodic:
    created = _parse_iso(payload["created_at"])
    updated_raw = payload.get("updated_at")
    updated = _parse_iso(updated_raw) if updated_raw else None
    archived_raw = payload.get("archived_at")
    archived = _parse_iso(archived_raw) if archived_raw else None
    return ArchivedEpisodic(
        memory_id=payload["memory_id"],
        content=payload["content"],
        layer=int(payload["layer"]),
        created_at=created,
        updated_at=updated,
        retention=float(payload["retention"]),
        importance=float(payload["importance"]),
        metadata=dict(payload.get("metadata") or {}),
        archived_at=archived,
    )


def _relative_path(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _iso(dt: datetime) -> str:
    return _ensure_utc(dt).isoformat()


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_iso(iso_str: str) -> datetime:
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _validate_unit_interval(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be in [0, 1], got {value!r}")
