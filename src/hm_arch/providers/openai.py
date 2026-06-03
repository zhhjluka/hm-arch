"""Optional OpenAI-compatible LLM and embedding providers."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from hm_arch.providers.errors import ProviderRuntimeError
from hm_arch.providers.http_common import (
    ProviderHTTPError,
    chat_completion_text,
    post_json,
)
from hm_arch.providers.local import LocalLLMProvider

_DEFAULT_BASE = "https://api.openai.com/v1"
_TRIPLE_LINE = re.compile(
    r"^\s*(?P<entity>[^|]+?)\s*\|\s*(?P<relation>[^|]+?)\s*\|\s*(?P<value>.+?)\s*$"
)


class OpenAILLMProvider:
    """OpenAI chat completions for importance and semantic extraction."""

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        timeout: float = 30.0,
        fallback_to_local: bool = True,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAI provider requires an API key")
        self._api_key = api_key
        self._model = model
        self._base_url = (base_url or _DEFAULT_BASE).rstrip("/")
        self._timeout = timeout
        self._fallback_to_local = fallback_to_local
        self._fallback = LocalLLMProvider()

    def score_importance(
        self,
        content: str,
        *,
        event_type: str = "conversation",
        metadata: dict | None = None,
    ) -> float:
        meta_hint = ""
        if metadata:
            meta_hint = f"\nMetadata: {json.dumps(metadata, ensure_ascii=False)}"
        prompt = (
            "Rate the long-term importance of this memory for an agent on a scale "
            "from 0.0 to 1.0. Reply with a single decimal number only.\n"
            f"Event type: {event_type}{meta_hint}\n\nMemory:\n{content}"
        )
        try:
            text = self._chat(prompt, system="You output only a number between 0 and 1.")
            value = float(text.split()[0])
            return max(0.0, min(1.0, value))
        except (ProviderHTTPError, ValueError) as exc:
            if self._fallback_to_local:
                return self._fallback.score_importance(
                    content, event_type=event_type, metadata=metadata
                )
            raise ProviderRuntimeError(
                "OpenAI LLM provider failed during importance scoring. "
                "Set provider_fallback_to_local=True to use local heuristics, "
                f"or fix the API error: {exc}"
            ) from exc

    def extract_semantic_triples(self, content: str) -> list[tuple[str, str, str]]:
        prompt = (
            "Extract semantic triples as lines: entity | relation | value\n"
            "Use lowercase entity 'user' for first-person references.\n"
            "Return one triple per line, or NONE if nothing extractable.\n\n"
            f"Text:\n{content}"
        )
        try:
            text = self._chat(
                prompt,
                system="You extract structured facts. Output only triple lines.",
            )
            triples = _parse_triple_lines(text)
            if triples:
                return triples
            if self._fallback_to_local:
                return self._fallback.extract_semantic_triples(content)
            raise ProviderRuntimeError(
                "OpenAI LLM provider returned no parseable semantic triples. "
                "Set provider_fallback_to_local=True to use the pattern extractor."
            )
        except ProviderHTTPError as exc:
            if self._fallback_to_local:
                return self._fallback.extract_semantic_triples(content)
            raise ProviderRuntimeError(
                "OpenAI LLM provider failed during semantic extraction. "
                "Set provider_fallback_to_local=True to use the pattern extractor, "
                f"or fix the API error: {exc}"
            ) from exc

    def _chat(self, user_prompt: str, *, system: str) -> str:
        url = f"{self._base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
        }
        response = post_json(
            url, payload, api_key=self._api_key, timeout=self._timeout
        )
        return chat_completion_text(response)


class OpenAIEmbeddingProvider:
    """OpenAI embeddings API."""

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        dimension: int,
        base_url: str | None = None,
        timeout: float = 30.0,
        fallback_to_local: bool = True,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAI embedding provider requires an API key")
        self._api_key = api_key
        self._model = model
        self._dimension = dimension
        self._base_url = (base_url or _DEFAULT_BASE).rstrip("/")
        self._timeout = timeout
        self._fallback_to_local = fallback_to_local
        from hm_arch.providers.local import LocalEmbeddingProvider

        self._local_fallback = LocalEmbeddingProvider(dimension=dimension)

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        url = f"{self._base_url}/embeddings"
        payload = {"model": self._model, "input": texts}
        try:
            response = post_json(
                url, payload, api_key=self._api_key, timeout=self._timeout
            )
        except ProviderHTTPError as exc:
            if self._fallback_to_local:
                return self._local_fallback.embed(texts)
            raise ProviderRuntimeError(
                "OpenAI embedding provider failed. "
                "Set provider_fallback_to_local=True to use local hash embeddings, "
                f"or fix the API error: {exc}"
            ) from exc
        data = response.get("data")
        if not isinstance(data, list):
            if self._fallback_to_local:
                return self._local_fallback.embed(texts)
            raise ProviderRuntimeError("Unexpected OpenAI embeddings response shape.")
        vectors = [item["embedding"] for item in sorted(data, key=lambda x: x["index"])]
        return vectors


def _parse_triple_lines(text: str) -> list[tuple[str, str, str]]:
    triples: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.upper() == "NONE":
            continue
        match = _TRIPLE_LINE.match(stripped)
        if match:
            triples.append(
                (
                    match.group("entity").strip(),
                    match.group("relation").strip(),
                    match.group("value").strip(),
                )
            )
    return triples


def openai_api_key_from_env() -> str | None:
    return os.environ.get("OPENAI_API_KEY") or os.environ.get("HM_ARCH_OPENAI_API_KEY")
