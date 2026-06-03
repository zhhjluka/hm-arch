"""Context-aware forgetting score from PRD retention and context factors."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import MemoryConfig
from ..storage.vector import _token_overlap_score, _tokenize


@dataclass(frozen=True)
class ContextAwareScore:
    """Decomposed forgetting score in ``[0, 1]`` (higher = more forgettable)."""

    retention: float
    relevance: float
    redundancy: float
    contradiction: float
    privacy: float
    composite: float


@dataclass(frozen=True)
class MemoryForgettingInput:
    """Inputs required to score one memory for context-aware forgetting."""

    memory_id: str
    content: str
    retention: float
    layer: int
    status: str
    metadata: dict
    neighbor_similarity: float = 0.0
    has_active_conflict: bool = False


def _relevance_to_context(query: str, content: str) -> float:
    if not query.strip():
        return 0.5
    return _token_overlap_score(_tokenize(query), _tokenize(content))


def _is_private(metadata: dict) -> bool:
    if metadata.get("private") is True:
        return True
    if metadata.get("privacy") in ("high", "strict", "pii"):
        return True
    tags = metadata.get("tags")
    if isinstance(tags, (list, tuple, set)):
        lowered = {str(tag).lower() for tag in tags}
        if lowered & {"private", "pii", "secret", "confidential"}:
            return True
    return False


def compute_context_aware_score(
    memory: MemoryForgettingInput,
    *,
    context_query: str = "",
    config: MemoryConfig | None = None,
) -> ContextAwareScore:
    """Compute a context-aware forgetting score for *memory*.

    The PRD factors are:

    * **retention** — weaker memories score higher.
    * **relevance** — content irrelevant to the current query scores higher.
    * **redundancy** — near-duplicate neighbours score higher.
    * **contradiction** — superseded or conflicting facts score higher.
    * **privacy** — private or sensitive rows score lower (protected).

    Parameters
    ----------
    memory:
        Snapshot of the memory row and optional neighbour similarity.
    context_query:
        Current retrieval or session query used for relevance scoring.
    config:
        Optional config supplying ``redundancy_threshold``.

    Returns
    -------
    ContextAwareScore
        Per-factor contributions and a composite score in ``[0, 1]``.
    """
    cfg = config or MemoryConfig()
    retention = max(0.0, min(1.0, float(memory.retention)))
    retention_factor = 1.0 - retention

    rel = _relevance_to_context(context_query, memory.content)
    relevance_factor = 1.0 - rel

    threshold = cfg.redundancy_threshold
    sim = max(0.0, min(1.0, float(memory.neighbor_similarity)))
    if sim <= threshold:
        redundancy_factor = 0.0
    else:
        redundancy_factor = (sim - threshold) / max(1e-9, 1.0 - threshold)

    contradiction_factor = 0.0
    if memory.status == "superseded" or memory.has_active_conflict:
        contradiction_factor = 1.0

    private = _is_private(memory.metadata)
    privacy_factor = 0.0 if private else 1.0

    composite = (
        retention_factor
        * (0.35 + 0.65 * relevance_factor)
        * (1.0 + 0.5 * redundancy_factor)
        * (1.0 + contradiction_factor)
        * privacy_factor
    )
    composite = max(0.0, min(1.0, composite))

    return ContextAwareScore(
        retention=retention_factor,
        relevance=relevance_factor,
        redundancy=redundancy_factor,
        contradiction=contradiction_factor,
        privacy=privacy_factor,
        composite=composite,
    )
