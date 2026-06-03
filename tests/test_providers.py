"""Tests for optional LLM/embedding providers and factories (MEM-30 / HM-30)."""

from __future__ import annotations

import json
from unittest import mock

import pytest

from hm_arch.config import MemoryConfig
from hm_arch.providers import (
    LocalEmbeddingProvider,
    LocalLLMProvider,
    ProviderConfigurationError,
    ProviderSemanticExtractor,
    create_vector_store,
    resolve_embedding_provider,
    resolve_llm_provider,
)
from hm_arch.providers.factory import resolve_api_key
from hm_arch.providers.openai import OpenAILLMProvider
from hm_arch.providers.protocol import EmbeddingProviderProtocol, LLMProviderProtocol
from hm_arch.storage.vector import LocalVectorStore, VectorStoreProtocol


class TestLocalProviders:
    def test_local_llm_satisfies_protocol(self) -> None:
        llm = LocalLLMProvider()
        assert isinstance(llm, LLMProviderProtocol)
        score = llm.score_importance("User prefers Python", event_type="conversation")
        assert 0.0 <= score <= 1.0

    def test_local_llm_extracts_pattern_triples(self) -> None:
        llm = LocalLLMProvider()
        triples = llm.extract_semantic_triples("User prefers Python")
        assert ("user", "prefers", "Python") in triples

    def test_local_embedding_deterministic(self) -> None:
        emb = LocalEmbeddingProvider(dimension=32)
        assert isinstance(emb, EmbeddingProviderProtocol)
        v1 = emb.embed(["hello world"])[0]
        v2 = emb.embed(["hello world"])[0]
        assert v1 == v2
        assert len(v1) == 32


class TestProviderFactory:
    def test_default_config_uses_local_llm(self) -> None:
        cfg = MemoryConfig()
        llm = resolve_llm_provider(cfg)
        assert llm.name == "local"

    def test_enable_without_key_falls_back_when_configured(self) -> None:
        cfg = MemoryConfig(
            enable_llm_providers=True,
            llm_provider="openai",
            provider_fallback_to_local=True,
            llm_api_key=None,
        )
        with mock.patch.dict("os.environ", {}, clear=True):
            llm = resolve_llm_provider(cfg)
        assert llm.name == "local"

    def test_enable_without_key_raises_when_no_fallback(self) -> None:
        cfg = MemoryConfig(
            enable_llm_providers=True,
            llm_provider="openai",
            provider_fallback_to_local=False,
            llm_api_key=None,
        )
        with mock.patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ProviderConfigurationError, match="API key"):
                resolve_llm_provider(cfg)

    def test_unknown_llm_provider_raises(self) -> None:
        cfg = MemoryConfig(llm_provider="anthropic")
        with pytest.raises(ProviderConfigurationError, match="Unknown llm_provider"):
            resolve_llm_provider(cfg)

    def test_create_vector_store_local_default(self) -> None:
        store = create_vector_store(MemoryConfig(), collection="l2_episodic")
        assert isinstance(store, LocalVectorStore)
        assert isinstance(store, VectorStoreProtocol)


class TestOpenAIProviderMocked:
    def test_score_importance_parses_response(self) -> None:
        llm = OpenAILLMProvider(api_key="test-key", model="gpt-4o-mini")
        response = {
            "choices": [{"message": {"content": "0.82"}}],
        }
        with mock.patch(
            "hm_arch.providers.openai.post_json",
            return_value=response,
        ):
            score = llm.score_importance("critical deployment failure")
        assert score == pytest.approx(0.82)

    def test_extract_semantic_triples_parses_lines(self) -> None:
        llm = OpenAILLMProvider(api_key="test-key", model="gpt-4o-mini")
        response = {
            "choices": [
                {
                    "message": {
                        "content": "user | prefers | Python\nuser | uses | SQLite"
                    }
                }
            ],
        }
        with mock.patch(
            "hm_arch.providers.openai.post_json",
            return_value=response,
        ):
            triples = llm.extract_semantic_triples("User prefers Python")
        assert ("user", "prefers", "Python") in triples
        assert ("user", "uses", "SQLite") in triples

    def test_http_failure_falls_back_to_local_importance(self) -> None:
        from hm_arch.providers.http_common import ProviderHTTPError

        llm = OpenAILLMProvider(api_key="test-key", model="gpt-4o-mini")
        with mock.patch(
            "hm_arch.providers.openai.post_json",
            side_effect=ProviderHTTPError("network down"),
        ):
            score = llm.score_importance("hello")
        local = LocalLLMProvider().score_importance("hello")
        assert score == pytest.approx(local)


class TestProviderSemanticExtractor:
    def test_delegates_to_llm_then_fallback(self) -> None:
        class FlakyLLM:
            name = "mock"

            def score_importance(self, content: str, **kwargs: object) -> float:
                return 0.5

            def extract_semantic_triples(self, content: str) -> list[tuple[str, str, str]]:
                if "fail" in content:
                    raise RuntimeError("provider down")
                return [("user", "likes", "tests")]

        fallback = mock.Mock()
        fallback.extract.return_value = [("user", "prefers", "Python")]
        extractor = ProviderSemanticExtractor(
            FlakyLLM(),  # type: ignore[arg-type]
            fallback=fallback,
        )
        assert extractor.extract("User likes tests") == [("user", "likes", "tests")]
        assert extractor.extract("fail trigger") == [("user", "prefers", "Python")]
        fallback.extract.assert_called_once_with("fail trigger")


class TestChromaVectorStoreMocked:
    def test_chroma_upsert_and_query_with_mock_client(self) -> None:
        fake_collection = mock.MagicMock()
        fake_collection.name = "hm_arch_l2_episodic"
        fake_client = mock.MagicMock()
        fake_client.get_or_create_collection.return_value = fake_collection

        fake_module = mock.MagicMock()
        fake_module.PersistentClient.return_value = fake_client

        emb = LocalEmbeddingProvider(dimension=16)
        with mock.patch.dict("sys.modules", {"chromadb": fake_module}):
            from hm_arch.storage.chroma import ChromaVectorStore

            store = ChromaVectorStore(
                persist_directory="/tmp/chroma-test",
                collection_name="hm_arch_l2_episodic",
                embedding_provider=emb,
            )
            store.upsert("id1", "Python data science", {"layer": 2})
            fake_collection.upsert.assert_called_once()

            fake_collection.query.return_value = {
                "ids": [["id1"]],
                "documents": [["Python data science"]],
                "metadatas": [[{"layer": 2}]],
                "distances": [[0.1]],
            }
            results = store.query("Python", top_k=1)
            assert results[0].id == "id1"
            assert results[0].score > 0.5

    def test_chroma_missing_dependency_raises_actionable_error(self) -> None:
        cfg = MemoryConfig(
            vector_backend="chroma",
            provider_fallback_to_local=False,
        )
        with mock.patch(
            "hm_arch.storage.chroma.chromadb",
            None,
            create=True,
        ):
            with pytest.raises(ImportError, match="chromadb"):
                create_vector_store(cfg, collection="l2_episodic")


def test_resolve_api_key_prefers_config() -> None:
    cfg = MemoryConfig(llm_api_key="from-config")
    assert resolve_api_key(cfg, "openai") == "from-config"
