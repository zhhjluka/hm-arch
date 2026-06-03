"""Agent session context — explicit L1 load/save and scoped rollback.

:class:`AgentContext` provides a stable API for persisting and restoring
in-session working memory (L1) via ``meta_memory``, plus a context manager
that rolls back ephemeral L1 changes after a scoped block.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterator

from .layers.base import LayerItem

if TYPE_CHECKING:
    from .core import HMArch

__all__ = ["AgentContext", "_SESSION_KEY"]

_SESSION_KEY = "hm_arch.agent_context.l1_session"


def _serialize_l1(items: list[LayerItem]) -> str:
    payload = [
        {
            "memory_id": item.memory_id,
            "layer": item.layer,
            "content": item.content,
            "added_at": item.added_at.isoformat(),
            "metadata": item.metadata,
        }
        for item in items
    ]
    return json.dumps(payload)


def _deserialize_l1(raw: str) -> list[LayerItem]:
    data = json.loads(raw)
    items: list[LayerItem] = []
    for entry in data:
        added_at = datetime.fromisoformat(entry["added_at"])
        if added_at.tzinfo is None:
            added_at = added_at.replace(tzinfo=timezone.utc)
        items.append(
            LayerItem(
                memory_id=entry["memory_id"],
                layer=int(entry["layer"]),
                content=entry["content"],
                added_at=added_at,
                metadata=dict(entry.get("metadata") or {}),
            )
        )
    return items


class AgentContext:
    """Stable session API for L1 working-memory persistence.

    Parameters
    ----------
    memory:
        Parent :class:`~hm_arch.core.HMArch` instance.

    Examples
    --------
    Explicit save/load across process restarts::

        ctx = AgentContext(memory)
        memory.add("baseline task")
        ctx.save_session()
        # ... later or new process ...
        ctx.load_session()

  Scoped rollback (same semantics as :meth:`HMArch.context`)::

        with AgentContext(memory):
            memory.add("temporary scratch note")
        # L1 restored; L2/L3 unchanged.
    """

    def __init__(self, memory: "HMArch") -> None:
        self._memory = memory

    @property
    def memory(self) -> "HMArch":
        """Parent :class:`~hm_arch.core.HMArch` instance (for scoped ``add`` / ``search``)."""
        return self._memory

    def save_session(self) -> None:
        """Persist the current L1 working-memory snapshot to ``meta_memory``."""
        payload = _serialize_l1(self._memory._l1.snapshot())
        now = datetime.now(tz=timezone.utc).isoformat()
        self._memory._db.execute(
            """
            INSERT INTO meta_memory (key, value, description, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                description = excluded.description,
                updated_at = excluded.updated_at
            """,
            (
                _SESSION_KEY,
                payload,
                "Serialized L1 working-memory session snapshot",
                now,
            ),
        )

    def load_session(self) -> bool:
        """Restore L1 from the last :meth:`save_session` payload.

        Returns
        -------
        bool
            ``True`` when a saved session was found and applied; ``False`` when
            no snapshot exists (L1 is left unchanged).
        """
        rows = self._memory._db.query(
            "SELECT value FROM meta_memory WHERE key = ?",
            (_SESSION_KEY,),
        )
        if not rows:
            return False
        items = _deserialize_l1(rows[0]["value"])
        self._memory._l1.load_snapshot(items)
        return True

    @contextmanager
    def scoped(self) -> Iterator["HMArch"]:
        """Context manager: rollback L1 to the pre-block snapshot on exit."""
        saved = self._memory._l1.snapshot()
        try:
            yield self._memory
        finally:
            self._memory._l1.load_snapshot(saved)

    @property
    def memory(self) -> "HMArch":
        """Parent :class:`~hm_arch.core.HMArch` instance."""
        return self._memory

    def __enter__(self) -> "AgentContext":
        self._saved_l1 = self._memory._l1.snapshot()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._memory._l1.load_snapshot(self._saved_l1)
