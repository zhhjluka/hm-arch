"""Structural protocols for optional LLM and embedding backends."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProviderProtocol(Protocol):
    """Minimal LLM surface for importance scoring and semantic extraction."""

    @property
    def name(self) -> str:
        """Provider identifier (e.g. ``"local"``, ``"openai"``)."""
        ...

    def score_importance(
        self,
        content: str,
        *,
        event_type: str = "conversation",
        metadata: dict | None = None,
    ) -> float:
        """Return importance in ``[0.0, 1.0]``."""
        ...

    def extract_semantic_triples(self, content: str) -> list[tuple[str, str, str]]:
        """Return ``(entity, relation, value)`` triples parsed from *content*."""
        ...


@runtime_checkable
class EmbeddingProviderProtocol(Protocol):
    """Embedding surface used by vector backends such as ChromaDB."""

    @property
    def name(self) -> str:
        """Provider identifier."""
        ...

    @property
    def dimension(self) -> int:
        """Vector dimensionality."""
        ...

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed one or more texts into dense vectors."""
        ...
