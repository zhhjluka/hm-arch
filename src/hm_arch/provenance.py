"""Memory provenance helpers for cross-agent sharing (MEM-53).

Provenance is persisted on ``memory_index`` columns and surfaced on public
search result types.  Legacy databases without dedicated columns still parse
from ``metadata["hm_arch_provenance"]`` when present.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

from .types import MemoryProvenance

_PROVENANCE_META_KEY = "hm_arch_provenance"


def build_provenance(
    *,
    agent: str | None = None,
    project: str | None = None,
    session: str | None = None,
    memory_type: str | None = None,
    created_at: datetime | None = None,
) -> MemoryProvenance:
    """Construct a :class:`MemoryProvenance` record for persistence."""
    when = created_at or datetime.now(tz=timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return MemoryProvenance(
        agent=agent,
        project=project,
        session=session,
        created_at=when,
        memory_type=memory_type,
    )


def merge_provenance_metadata(
    metadata: dict | None,
    provenance: MemoryProvenance,
) -> dict:
    """Return caller metadata merged with a namespaced provenance block."""
    base = dict(metadata) if metadata else {}
    base[_PROVENANCE_META_KEY] = provenance_to_metadata_dict(provenance)
    return base


def provenance_to_metadata_dict(provenance: MemoryProvenance) -> dict:
    """Serialize provenance for JSON metadata storage."""
    return {
        "agent": provenance.agent,
        "project": provenance.project,
        "session": provenance.session,
        "created_at": provenance.created_at.isoformat(),
        "memory_type": provenance.memory_type,
    }


def parse_provenance_row(
    row: Mapping[str, object],
    *,
    fallback_memory_type: str | None = None,
) -> MemoryProvenance | None:
    """Build provenance from a ``memory_index`` row or compatible mapping."""
    data = _row_as_mapping(row)
    created_raw = data.get("created_at")
    if created_raw is None:
        return None

    agent = _optional_str(data.get("provenance_agent"))
    project = _optional_str(data.get("provenance_project"))
    session = _optional_str(data.get("provenance_session"))
    memory_type = _optional_str(data.get("memory_type")) or fallback_memory_type

    metadata_raw = data.get("metadata")
    if metadata_raw and (agent is None and project is None and session is None):
        meta_block = _provenance_from_metadata(metadata_raw)
        if meta_block is not None:
            agent = agent or meta_block.agent
            project = project or meta_block.project
            session = session or meta_block.session
            memory_type = memory_type or meta_block.memory_type

    if (
        agent is None
        and project is None
        and session is None
        and memory_type is None
    ):
        return None

    return MemoryProvenance(
        agent=agent,
        project=project,
        session=session,
        created_at=_parse_iso(str(created_raw)),
        memory_type=memory_type,
    )


def _row_as_mapping(row: Mapping[str, object]) -> dict[str, object]:
    if isinstance(row, dict):
        return row
    try:
        return dict(row)  # sqlite3.Row and other mappings
    except TypeError:
        return {}


def provenance_column_values(
    provenance: MemoryProvenance | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Return SQL column values for provenance fields on ``memory_index``."""
    if provenance is None:
        return (None, None, None, None)
    return (
        provenance.agent,
        provenance.project,
        provenance.session,
        provenance.memory_type,
    )


def _provenance_from_metadata(metadata_raw: object) -> MemoryProvenance | None:
    if not isinstance(metadata_raw, str):
        return None
    try:
        import json

        payload = json.loads(metadata_raw or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    block = payload.get(_PROVENANCE_META_KEY)
    if not isinstance(block, dict):
        return None
    created_raw = block.get("created_at")
    created_at = (
        _parse_iso(str(created_raw))
        if created_raw is not None
        else datetime.now(tz=timezone.utc)
    )
    return MemoryProvenance(
        agent=_optional_str(block.get("agent")),
        project=_optional_str(block.get("project")),
        session=_optional_str(block.get("session")),
        created_at=created_at,
        memory_type=_optional_str(block.get("memory_type")),
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_iso(iso_str: str) -> datetime:
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
