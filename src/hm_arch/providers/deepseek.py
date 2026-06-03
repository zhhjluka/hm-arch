"""Optional DeepSeek LLM and embedding providers (OpenAI-compatible API)."""

from __future__ import annotations

import os

from hm_arch.providers.openai import OpenAIEmbeddingProvider, OpenAILLMProvider

_DEFAULT_BASE = "https://api.deepseek.com/v1"


class DeepSeekLLMProvider(OpenAILLMProvider):
    """DeepSeek chat API (OpenAI-compatible)."""

    name = "deepseek"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url or _DEFAULT_BASE,
            timeout=timeout,
        )
        self.name = "deepseek"


class DeepSeekEmbeddingProvider(OpenAIEmbeddingProvider):
    """DeepSeek embeddings API (OpenAI-compatible)."""

    name = "deepseek"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        dimension: int,
        base_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            dimension=dimension,
            base_url=base_url or _DEFAULT_BASE,
            timeout=timeout,
        )
        self.name = "deepseek"


def deepseek_api_key_from_env() -> str | None:
    return os.environ.get("DEEPSEEK_API_KEY") or os.environ.get(
        "HM_ARCH_DEEPSEEK_API_KEY"
    )
