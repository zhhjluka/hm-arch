"""Recall context formatting for agent turn-start hooks."""

from __future__ import annotations

from hm_arch import HMArch
from hm_arch.types import SearchResult

_STORAGE_SCOPE_META = "hm_arch_storage_scope"


def build_turn_start_context(
    memory: HMArch,
    task: str,
    *,
    top_k: int = 5,
    hits: SearchResult | None = None,
) -> str:
    """Search durable memory and format context text for turn-start injection."""
    task = task.strip()
    if not task:
        return ""

    search_hits = hits if hits is not None else memory.search(task, top_k=top_k)
    if not search_hits.results:
        return ""

    lines = ["## HM-Arch memory context", ""]
    for index, item in enumerate(search_hits.results, start=1):
        store = item.metadata.get(_STORAGE_SCOPE_META)
        store_label = f"|{store}" if store else ""
        provenance_bits: list[str] = []
        if item.provenance is not None:
            prov = item.provenance
            if prov.agent:
                provenance_bits.append(f"agent={prov.agent}")
            if prov.project:
                provenance_bits.append(f"project={prov.project}")
            if prov.session:
                provenance_bits.append(f"session={prov.session}")
            if prov.memory_type:
                provenance_bits.append(f"type={prov.memory_type}")
        provenance_label = (
            f" ({', '.join(provenance_bits)})" if provenance_bits else ""
        )
        lines.append(
            f"{index}. [L{item.layer}{store_label}] {item.content} "
            f"(retention={item.retention:.2f}, score={item.score:.2f})"
            f"{provenance_label}"
        )
    return "\n".join(lines)
