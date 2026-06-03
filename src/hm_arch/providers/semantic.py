"""Semantic extraction adapters that delegate to LLM providers."""

from __future__ import annotations

from hm_arch.consolidation.replay import SemanticExtractor
from hm_arch.providers.protocol import LLMProviderProtocol


class ProviderSemanticExtractor:
    """Wraps an :class:`~hm_arch.providers.protocol.LLMProviderProtocol` for consolidation.

  Falls back to pattern-based :class:`SemanticExtractor` on provider errors.
    """

    def __init__(
        self,
        llm: LLMProviderProtocol,
        *,
        fallback: SemanticExtractor | None = None,
    ) -> None:
        self._llm = llm
        self._fallback = fallback or SemanticExtractor()

    def extract(self, content: str) -> list[tuple[str, str, str]]:
        try:
            triples = self._llm.extract_semantic_triples(content)
            if triples:
                return triples
        except Exception:
            pass
        return self._fallback.extract(content)
