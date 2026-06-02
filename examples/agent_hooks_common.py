"""Shared offline hook logic for Codex and Claude Code examples.

Portable paths only: use ``HM_ARCH_DB_PATH`` or a caller-supplied path.
No machine-specific home-directory defaults.
"""

from __future__ import annotations

import os
from pathlib import Path

from hm_arch import EventType, HMArch, MemoryConfig
from hm_arch.types import ConsolidationReport


def resolve_db_path(explicit: str | None = None) -> str:
    """Return the SQLite path for hook scripts.

    Priority: *explicit* argument, ``HM_ARCH_DB_PATH`` env var, then
    ``./.hm_arch_agent_memory.db`` under the current working directory.
    """
    if explicit is not None:
        return explicit
    env_path = os.environ.get("HM_ARCH_DB_PATH")
    if env_path:
        return env_path
    return str(Path.cwd() / ".hm_arch_agent_memory.db")


def open_memory(
    db_path: str | None = None,
    *,
    replay_sample_ratio: float = 1.0,
) -> HMArch:
    """Open an :class:`~hm_arch.core.HMArch` store for hook handlers."""
    path = resolve_db_path(db_path)
    config = MemoryConfig(db_path=path, replay_sample_ratio=replay_sample_ratio)
    return HMArch(config=config)


def build_turn_start_context(
    memory: HMArch,
    task: str,
    *,
    top_k: int = 5,
) -> str:
    """Search durable memory and format context text for turn-start injection."""
    task = task.strip()
    if not task:
        return ""

    hits = memory.search(task, top_k=top_k)
    if not hits.results:
        return ""

    lines = ["## HM-Arch memory context", ""]
    for index, item in enumerate(hits.results, start=1):
        lines.append(
            f"{index}. [L{item.layer}] {item.content} "
            f"(retention={item.retention:.2f}, score={item.score:.2f})"
        )
    return "\n".join(lines)


def record_turn_end(
    memory: HMArch,
    user_message: str,
    agent_message: str,
) -> list[str]:
    """Persist user and assistant messages from a completed turn."""
    recorded: list[str] = []
    user_message = user_message.strip()
    agent_message = agent_message.strip()

    if user_message:
        receipt = memory.add(
            f"User: {user_message}",
            event_type=EventType.CONVERSATION,
            importance=0.7,
        )
        recorded.append(receipt.memory_id)

    if agent_message:
        receipt = memory.add(
            f"Assistant: {agent_message}",
            event_type=EventType.CONVERSATION,
            importance=0.6,
        )
        recorded.append(receipt.memory_id)

    return recorded


def run_idle_consolidation(memory: HMArch) -> ConsolidationReport:
    """Run offline sleep consolidation (safe on an empty store)."""
    return memory.consolidate()


def extract_task_from_payload(payload: dict) -> str:
    """Best-effort task/prompt extraction from hook JSON payloads."""
    for key in (
        "prompt",
        "user_prompt",
        "user_message",
        "message",
        "task",
        "input",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def extract_user_message(payload: dict) -> str:
    for key in ("user_message", "user_prompt", "prompt", "message"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def extract_agent_message(payload: dict) -> str:
    for key in (
        "last_assistant_message",
        "assistant_message",
        "agent_message",
        "response",
        "output",
    ):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""
