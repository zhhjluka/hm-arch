"""Optional DeepSeek LLM provider (OpenAI-compatible chat API)."""

from __future__ import annotations

import os

from hm_arch.providers.openai import OpenAILLMProvider

_DEFAULT_BASE = "https://api.deepseek.com/v1"


class DeepSeekLLMProvider(OpenAILLMProvider):
    """DeepSeek chat API (OpenAI-compatible).

    DeepSeek's documented API covers chat completions only — there is no
  official embeddings endpoint.  Use ``embedding_provider='local'`` or
  ``'openai'`` for vector backends.
    """

    name = "deepseek"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        timeout: float = 30.0,
        fallback_to_local: bool = True,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url or _DEFAULT_BASE,
            timeout=timeout,
            fallback_to_local=fallback_to_local,
        )
        self.name = "deepseek"


def deepseek_api_key_from_env() -> str | None:
    return os.environ.get("DEEPSEEK_API_KEY") or os.environ.get(
        "HM_ARCH_DEEPSEEK_API_KEY"
    )
