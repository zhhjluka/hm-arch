"""Semantic extraction adapters that delegate to LLM providers."""

from __future__ import annotations

from hm_arch.consolidation.replay import SemanticExtractor
from hm_arch.providers.errors import ProviderRuntimeError
from hm_arch.providers.protocol import LLMProviderProtocol


class ProviderSemanticExtractor:
    """Wraps an :class:`~hm_arch.providers.protocol.LLMProviderProtocol` for consolidation.

    When ``fallback_to_local`` is ``True``, pattern-based
    :class:`SemanticExtractor` is used on provider errors or empty LLM output.
    When ``False``, failures propagate as :class:`ProviderRuntimeError`.
    """

    def __init__(
        self,
        llm: LLMProviderProtocol,
        *,
        fallback: SemanticExtractor | None = None,
        fallback_to_local: bool = True,
    ) -> None:
        self._llm = llm
        self._fallback = fallback or SemanticExtractor()
        self._fallback_to_local = fallback_to_local

    def extract(self, content: str) -> list[tuple[str, str, str]]:
        try:
            triples = self._llm.extract_semantic_triples(content)
            if triples:
                return triples
            if self._fallback_to_local:
                return self._fallback.extract(content)
            raise ProviderRuntimeError(
                "LLM provider returned no semantic triples and "
                "provider_fallback_to_local=False. "
                "Enable fallback or adjust the provider prompt/model."
            )
        except ProviderRuntimeError:
            raise
        except Exception as exc:
            if self._fallback_to_local:
                return self._fallback.extract(content)
            raise ProviderRuntimeError(
                "LLM provider failed during semantic extraction and "
                "provider_fallback_to_local=False. "
                "Enable fallback or fix the provider error."
            ) from exc
