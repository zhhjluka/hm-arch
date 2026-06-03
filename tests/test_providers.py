"""Tests for optional LLM/embedding providers and factories (MEM-30 / HM-30)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

import pytest

from hm_arch import HMArch, MemoryConfig
from hm_arch.config import MemoryConfig as MC
from hm_arch.consolidation import ConsolidationEngine
from hm_arch.providers import (
    LocalEmbeddingProvider,
    LocalLLMProvider,
    ProviderConfigurationError,
    ProviderRuntimeError,
    ProviderSemanticExtractor,
    create_vector_store,
    resolve_embedding_provider,
    resolve_llm_model,
    resolve_llm_provider,
)
from hm_arch.providers.factory import resolve_api_key, resolve_embedding_model
from hm_arch.providers.openai import OpenAILLMProvider
from hm_arch.providers.protocol import EmbeddingProviderProtocol, LLMProviderProtocol
from hm_arch.storage.sqlite import SQLiteStore
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

    def test_openai_default_model_when_unset(self) -> None:
        cfg = MemoryConfig(
            enable_llm_providers=True,
            llm_provider="openai",
            llm_api_key="key",
            llm_model=None,
        )
        assert resolve_llm_model(cfg, "openai") == "gpt-4o-mini"

    def test_deepseek_default_model_when_unset(self) -> None:
        cfg = MemoryConfig(
            enable_llm_providers=True,
            llm_provider="deepseek",
            llm_api_key="key",
            llm_model=None,
        )
        assert resolve_llm_model(cfg, "deepseek") == "deepseek-chat"

    def test_openai_default_embedding_model_when_unset(self) -> None:
        cfg = MemoryConfig(
            enable_llm_providers=True,
            embedding_provider="openai",
            llm_api_key="key",
            embedding_model=None,
        )
        assert resolve_embedding_model(cfg, "openai") == "text-embedding-3-small"

    def test_deepseek_embedding_unsupported_without_fallback(self) -> None:
        cfg = MemoryConfig(
            enable_llm_providers=True,
            embedding_provider="deepseek",
            llm_api_key="key",
            provider_fallback_to_local=False,
        )
        with pytest.raises(ProviderConfigurationError, match="not supported"):
            resolve_embedding_provider(cfg)

    def test_deepseek_embedding_falls_back_to_local_when_enabled(self) -> None:
        cfg = MemoryConfig(
            enable_llm_providers=True,
            embedding_provider="deepseek",
            llm_api_key="key",
            provider_fallback_to_local=True,
        )
        emb = resolve_embedding_provider(cfg)
        assert isinstance(emb, LocalEmbeddingProvider)

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
        llm = OpenAILLMProvider(
            api_key="test-key", model="gpt-4o-mini", fallback_to_local=False
        )
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

    def test_http_failure_falls_back_when_enabled(self) -> None:
        from hm_arch.providers.http_common import ProviderHTTPError

        llm = OpenAILLMProvider(
            api_key="test-key",
            model="gpt-4o-mini",
            fallback_to_local=True,
        )
        with mock.patch(
            "hm_arch.providers.openai.post_json",
            side_effect=ProviderHTTPError("network down"),
        ):
            score = llm.score_importance("hello")
        local = LocalLLMProvider().score_importance("hello")
        assert score == pytest.approx(local)

    def test_http_failure_raises_when_fallback_disabled(self) -> None:
        from hm_arch.providers.http_common import ProviderHTTPError

        llm = OpenAILLMProvider(
            api_key="test-key",
            model="gpt-4o-mini",
            fallback_to_local=False,
        )
        with mock.patch(
            "hm_arch.providers.openai.post_json",
            side_effect=ProviderHTTPError("network down"),
        ):
            with pytest.raises(ProviderRuntimeError, match="importance scoring"):
                llm.score_importance("hello")

    def test_extraction_http_failure_raises_when_fallback_disabled(self) -> None:
        from hm_arch.providers.http_common import ProviderHTTPError

        llm = OpenAILLMProvider(
            api_key="test-key",
            model="gpt-4o-mini",
            fallback_to_local=False,
        )
        with mock.patch(
            "hm_arch.providers.openai.post_json",
            side_effect=ProviderHTTPError("network down"),
        ):
            with pytest.raises(ProviderRuntimeError, match="semantic extraction"):
                llm.extract_semantic_triples("User prefers Python")


class TestProviderSemanticExtractor:
    def test_delegates_to_llm_then_fallback_when_enabled(self) -> None:
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
            fallback_to_local=True,
        )
        assert extractor.extract("User likes tests") == [("user", "likes", "tests")]
        assert extractor.extract("fail trigger") == [("user", "prefers", "Python")]
        fallback.extract.assert_called_once_with("fail trigger")

    def test_raises_when_fallback_disabled(self) -> None:
        class FlakyLLM:
            name = "mock"

            def score_importance(self, content: str, **kwargs: object) -> float:
                return 0.5

            def extract_semantic_triples(self, content: str) -> list[tuple[str, str, str]]:
                raise RuntimeError("provider down")

        extractor = ProviderSemanticExtractor(
            FlakyLLM(),  # type: ignore[arg-type]
            fallback_to_local=False,
        )
        with pytest.raises(ProviderRuntimeError, match="semantic extraction"):
            extractor.extract("any content")


class TestHMArchProviderFallback:
    def test_add_raises_on_provider_failure_without_fallback(self) -> None:
        from hm_arch.providers.http_common import ProviderHTTPError

        cfg = MemoryConfig(
            enable_llm_providers=True,
            llm_provider="openai",
            llm_api_key="test-key",
            provider_fallback_to_local=False,
        )
        mem = HMArch(db_path=":memory:", config=cfg)
        try:
            with mock.patch(
                "hm_arch.providers.openai.post_json",
                side_effect=ProviderHTTPError("network down"),
            ):
                with pytest.raises(ProviderRuntimeError):
                    mem.add("probe content for provider failure")
        finally:
            mem.close()

    def test_add_succeeds_with_local_fallback_on_provider_failure(self) -> None:
        from hm_arch.providers.http_common import ProviderHTTPError

        cfg = MemoryConfig(
            enable_llm_providers=True,
            llm_provider="openai",
            llm_api_key="test-key",
            provider_fallback_to_local=True,
        )
        mem = HMArch(db_path=":memory:", config=cfg)
        try:
            with mock.patch(
                "hm_arch.providers.openai.post_json",
                side_effect=ProviderHTTPError("network down"),
            ):
                receipt = mem.add("probe content for local fallback")
            assert receipt.memory_id
        finally:
            mem.close()

    def test_consolidate_raises_on_extraction_failure_without_fallback(self) -> None:
        from hm_arch.providers.http_common import ProviderHTTPError

        cfg = MemoryConfig(
            enable_llm_providers=True,
            llm_provider="openai",
            llm_api_key="test-key",
            provider_fallback_to_local=False,
            replay_sample_ratio=1.0,
        )
        mem = HMArch(db_path=":memory:", config=cfg)
        try:
            mem.add("User prefers Python", importance=0.5)
            with mock.patch(
                "hm_arch.providers.openai.post_json",
                side_effect=ProviderHTTPError("network down"),
            ):
                with pytest.raises(ProviderRuntimeError):
                    mem.consolidate()
        finally:
            mem.close()


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


class TestChromaPersistence:
    """Offline persistence using an in-memory fake Chroma client."""

    @staticmethod
    def _install_fake_chromadb() -> dict:
        collections: dict[tuple[str, str], mock.MagicMock] = {}

        def make_collection(name: str) -> mock.MagicMock:
            col = mock.MagicMock()
            col.name = name
            storage: dict[str, dict] = {}

            def upsert(*, ids, documents, metadatas, embeddings) -> None:
                for i, doc_id in enumerate(ids):
                    storage[doc_id] = {
                        "document": documents[i],
                        "metadata": dict(metadatas[i]),
                        "embedding": embeddings[i],
                    }

            def query(*, query_embeddings, n_results, where=None) -> dict:
                hits = []
                for doc_id, row in storage.items():
                    if where:
                        if not all(row["metadata"].get(k) == v for k, v in where.items()):
                            continue
                    hits.append((doc_id, row))
                hits = hits[:n_results]
                return {
                    "ids": [[h[0] for h in hits]],
                    "documents": [[h[1]["document"] for h in hits]],
                    "metadatas": [[h[1]["metadata"] for h in hits]],
                    "distances": [[0.05 for _ in hits]],
                }

            def get(*, ids) -> dict:
                found = [i for i in ids if i in storage]
                return {
                    "ids": found,
                    "documents": [storage[i]["document"] for i in found],
                    "metadatas": [storage[i]["metadata"] for i in found],
                }

            def delete(*, ids) -> None:
                for doc_id in ids:
                    storage.pop(doc_id, None)

            col.upsert.side_effect = upsert
            col.query.side_effect = query
            col.get.side_effect = get
            col.delete.side_effect = delete
            col._storage = storage
            return col

        class FakeClient:
            def __init__(self, path: str) -> None:
                self.path = path

            def get_or_create_collection(self, name: str, metadata=None) -> mock.MagicMock:
                key = (self.path, name)
                if key not in collections:
                    collections[key] = make_collection(name)
                return collections[key]

            def delete_collection(self, name: str) -> None:
                to_drop = [k for k in collections if k[1] == name]
                for key in to_drop:
                    del collections[key]

        fake_module = mock.MagicMock()
        fake_module.PersistentClient.side_effect = FakeClient
        return {"chromadb": fake_module, "collections": collections}

    def test_l2_l3_chroma_collections_persist_and_reopen(self) -> None:
        from hm_arch.layers.l2_episodic import L2EpisodicBuffer
        from hm_arch.layers.l3_semantic import L3SemanticMemory

        fake = self._install_fake_chromadb()
        with tempfile.TemporaryDirectory() as tmpdir:
            chroma_dir = str(Path(tmpdir) / "chroma")
            db_path = str(Path(tmpdir) / "mem.db")
            cfg = MC(
                db_path=db_path,
                vector_backend="chroma",
                chroma_persist_directory=chroma_dir,
            )

            with mock.patch.dict("sys.modules", {"chromadb": fake["chromadb"]}):
                db = SQLiteStore(db_path).connect()
                db.initialize_schema()
                l2_store = create_vector_store(cfg, collection="l2_episodic")
                l3_store = create_vector_store(cfg, collection="l3_semantic")
                l2 = L2EpisodicBuffer(db, vector_store=l2_store)
                mid = l2.encode("User prefers Python for data science")
                l3 = L3SemanticMemory(db, vector_store=l3_store, config=cfg)
                l3.upsert("user", "prefers", "Python", source_episodes=[mid])

                l2_hits = l2_store.query("Python data", top_k=3)
                l3_hits = l3_store.query("Python", top_k=3)
                assert l2_hits
                assert l3_hits

                db.close()

                db2 = SQLiteStore(db_path).connect()
                l2_store2 = create_vector_store(cfg, collection="l2_episodic")
                l3_store2 = create_vector_store(cfg, collection="l3_semantic")
                l2_reopened = L2EpisodicBuffer(db2, vector_store=l2_store2)
                l3_reopened = L3SemanticMemory(db2, vector_store=l3_store2, config=cfg)

                assert l2_reopened.retrieve("Python data", top_k=3)
                assert l3_reopened.search("Python", top_k=3)
                db2.close()

    def test_hmarch_chroma_reopen_search_via_sqlite_rebuild(self) -> None:
        fake = self._install_fake_chromadb()
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "mem.db")
            cfg = MC(
                db_path=db_path,
                vector_backend="chroma",
                chroma_persist_directory=str(Path(tmpdir) / "chroma"),
            )
            with mock.patch.dict("sys.modules", {"chromadb": fake["chromadb"]}):
                m1 = HMArch(db_path=db_path, config=cfg)
                m1.add("persistent Python preference for testing")
                m1.close()

                m2 = HMArch(db_path=db_path, config=cfg)
                try:
                    result = m2.search("Python preference", top_k=5, min_retention=0.0)
                    assert any(
                        "Python" in item.content for item in result.results
                    ), result.results
                finally:
                    m2.close()


def test_resolve_api_key_prefers_config() -> None:
    cfg = MemoryConfig(llm_api_key="from-config")
    assert resolve_api_key(cfg, "openai") == "from-config"
