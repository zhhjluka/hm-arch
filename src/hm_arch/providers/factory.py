"""Resolve optional LLM/embedding providers with graceful local fallback."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from hm_arch.providers.deepseek import (
    DeepSeekEmbeddingProvider,
    DeepSeekLLMProvider,
    deepseek_api_key_from_env,
)
from hm_arch.providers.local import LocalEmbeddingProvider, LocalLLMProvider
from hm_arch.providers.openai import (
    OpenAIEmbeddingProvider,
    OpenAILLMProvider,
    openai_api_key_from_env,
)
from hm_arch.providers.protocol import (
    EmbeddingProviderProtocol,
    LLMProviderProtocol,
)

if TYPE_CHECKING:
    from hm_arch.config import MemoryConfig

_VALID_LLM = frozenset({"local", "deepseek", "openai"})
_VALID_EMBEDDING = frozenset({"local", "deepseek", "openai"})
_VALID_VECTOR = frozenset({"local", "chroma"})


class ProviderConfigurationError(ValueError):
    """Raised when provider settings are inconsistent and fallback is disabled."""


def resolve_api_key(config: MemoryConfig, provider: str) -> str | None:
    """Return an API key from config or well-known environment variables."""
    if config.llm_api_key:
        return config.llm_api_key
    if provider == "openai":
        return openai_api_key_from_env()
    if provider == "deepseek":
        return deepseek_api_key_from_env()
    env_key = os.environ.get("HM_ARCH_API_KEY")
    return env_key


def resolve_llm_provider(config: MemoryConfig) -> LLMProviderProtocol:
    """Return the configured LLM provider, falling back to local when appropriate.

    Provider-backed scoring is **opt-in** via ``config.enable_llm_providers``.
    Without that flag, or without credentials, :class:`LocalLLMProvider` is used.
    """
    provider = config.llm_provider.lower().strip()
    if provider not in _VALID_LLM:
        raise ProviderConfigurationError(
            f"Unknown llm_provider {config.llm_provider!r}. "
            f"Choose from: {sorted(_VALID_LLM)}"
        )

    if provider == "local" or not config.enable_llm_providers:
        return LocalLLMProvider()

    api_key = resolve_api_key(config, provider)
    if not api_key:
        if config.provider_fallback_to_local:
            return LocalLLMProvider()
        raise ProviderConfigurationError(
            f"llm_provider={provider!r} requires an API key. Set "
            "MemoryConfig.llm_api_key or the provider environment variable, "
            "or set provider_fallback_to_local=True to use local heuristics."
        )

    base_url = config.llm_base_url
    if provider == "openai":
        return OpenAILLMProvider(
            api_key=api_key,
            model=config.llm_model,
            base_url=base_url,
        )
    return DeepSeekLLMProvider(
        api_key=api_key,
        model=config.llm_model,
        base_url=base_url,
    )


def resolve_embedding_provider(config: MemoryConfig) -> EmbeddingProviderProtocol:
    """Return the configured embedding provider with local fallback."""
    provider = config.embedding_provider.lower().strip()
    if provider not in _VALID_EMBEDDING:
        raise ProviderConfigurationError(
            f"Unknown embedding_provider {config.embedding_provider!r}. "
            f"Choose from: {sorted(_VALID_EMBEDDING)}"
        )

    if provider == "local" or not config.enable_llm_providers:
        return LocalEmbeddingProvider(dimension=config.embedding_dim)

    api_key = resolve_api_key(config, provider)
    if not api_key:
        if config.provider_fallback_to_local:
            return LocalEmbeddingProvider(dimension=config.embedding_dim)
        raise ProviderConfigurationError(
            f"embedding_provider={provider!r} requires an API key when "
            "enable_llm_providers=True. Set llm_api_key or enable "
            "provider_fallback_to_local=True."
        )

    base_url = config.llm_base_url
    if provider == "openai":
        return OpenAIEmbeddingProvider(
            api_key=api_key,
            model=config.embedding_model,
            dimension=config.embedding_dim,
            base_url=base_url,
        )
    return DeepSeekEmbeddingProvider(
        api_key=api_key,
        model=config.embedding_model,
        dimension=config.embedding_dim,
        base_url=base_url,
    )


def create_vector_store(
    config: MemoryConfig,
    *,
    collection: str,
):
    """Instantiate a vector store backend from *config*.

    Parameters
    ----------
    collection:
        Logical collection name (e.g. ``"l2_episodic"``, ``"l3_semantic"``).
    """
    backend = config.vector_backend.lower().strip()
    if backend not in _VALID_VECTOR:
        raise ProviderConfigurationError(
            f"Unknown vector_backend {config.vector_backend!r}. "
            f"Choose from: {sorted(_VALID_VECTOR)}"
        )

    if backend == "local":
        from hm_arch.storage.vector import LocalVectorStore

        return LocalVectorStore()

    try:
        from hm_arch.storage.chroma import ChromaVectorStore
    except ImportError as exc:
        if config.provider_fallback_to_local:
            from hm_arch.storage.vector import LocalVectorStore

            return LocalVectorStore()
        raise ImportError(
            "ChromaDB vector backend requires the optional 'chromadb' package. "
            "Install with: pip install 'hm-arch[chroma]' "
            "or set vector_backend='local' / provider_fallback_to_local=True."
        ) from exc

    persist_dir = config.chroma_persist_directory
    if persist_dir is None:
        parent = os.path.dirname(os.path.abspath(config.db_path))
        if config.db_path == ":memory:":
            parent = os.path.abspath("./.agent_memory_data")
        persist_dir = os.path.join(parent, "chroma")

    embedder = resolve_embedding_provider(config)
    prefix = config.chroma_collection_prefix.strip() or "hm_arch"
    full_name = f"{prefix}_{collection}"
    try:
        return ChromaVectorStore(
            persist_directory=persist_dir,
            collection_name=full_name,
            embedding_provider=embedder,
        )
    except ImportError as exc:
        if config.provider_fallback_to_local:
            from hm_arch.storage.vector import LocalVectorStore

            return LocalVectorStore()
        raise ImportError(
            "ChromaDB vector backend requires the optional 'chromadb' package. "
            "Install with: pip install 'hm-arch[chroma]' "
            "or set vector_backend='local' / provider_fallback_to_local=True."
        ) from exc
