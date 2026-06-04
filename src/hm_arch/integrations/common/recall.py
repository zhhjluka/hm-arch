"""Recall context formatting for agent turn-start hooks."""

from __future__ import annotations

from hm_arch import HMArch


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
