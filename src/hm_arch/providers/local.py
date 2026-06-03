"""Deterministic local LLM and embedding fallbacks (no network, no API keys)."""

from __future__ import annotations

import hashlib
import math
import re

from hm_arch.consolidation.replay import SemanticExtractor
from hm_arch.forgetting.strength import score_local_importance
from hm_arch.types import EventType

_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


class LocalLLMProvider:
    """Pattern/heuristic importance and semantic extraction without an LLM."""

    name = "local"

    def __init__(self, extractor: SemanticExtractor | None = None) -> None:
        self._extractor = extractor or SemanticExtractor()

    def score_importance(
        self,
        content: str,
        *,
        event_type: str = "conversation",
        metadata: dict | None = None,
    ) -> float:
        try:
            et = EventType(event_type)
        except ValueError:
            et = EventType.CONVERSATION
        return score_local_importance(content, event_type=et, metadata=metadata)

    def extract_semantic_triples(self, content: str) -> list[tuple[str, str, str]]:
        return self._extractor.extract(content)


class LocalEmbeddingProvider:
    """Hash-based deterministic embeddings for offline vector backends."""

    name = "local"

    def __init__(self, dimension: int = 384) -> None:
        if dimension < 8:
            raise ValueError("embedding dimension must be at least 8")
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_hash_embed(text, self._dimension) for text in texts]


def _hash_embed(text: str, dimension: int) -> list[float]:
    """Map text to a unit-normalized vector via salted SHA-256 buckets."""
    tokens = _TOKEN_RE.findall(text.lower()) or [text.lower() or ""]
    vec = [0.0] * dimension
    for token in tokens:
        digest = hashlib.sha256(token.encode()).digest()
        for i in range(dimension):
            byte = digest[i % len(digest)]
            vec[i] += (byte / 127.5) - 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]
