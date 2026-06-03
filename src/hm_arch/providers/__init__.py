"""Optional LLM, embedding, and vector backend factories."""

from hm_arch.providers.errors import ProviderRuntimeError
from hm_arch.providers.factory import (
    ProviderConfigurationError,
    create_vector_store,
    resolve_api_key,
    resolve_embedding_model,
    resolve_embedding_provider,
    resolve_llm_model,
    resolve_llm_provider,
)
from hm_arch.providers.local import LocalEmbeddingProvider, LocalLLMProvider
from hm_arch.providers.protocol import EmbeddingProviderProtocol, LLMProviderProtocol
from hm_arch.providers.semantic import ProviderSemanticExtractor

__all__ = [
    "EmbeddingProviderProtocol",
    "LLMProviderProtocol",
    "LocalEmbeddingProvider",
    "LocalLLMProvider",
    "ProviderConfigurationError",
    "ProviderRuntimeError",
    "ProviderSemanticExtractor",
    "create_vector_store",
    "resolve_api_key",
    "resolve_embedding_model",
    "resolve_embedding_provider",
    "resolve_llm_model",
    "resolve_llm_provider",
]
