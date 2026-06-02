"""Tests for the vector store abstraction — MEM-9 (HM-4).

Design principles
-----------------
* All tests are fully offline: no external API keys, no ChromaDB, no network.
* Tests validate the acceptance criteria from MEM-9:
  - Upsert / query / delete work correctly.
  - Query returns stable, deterministic relevance ordering.
  - Metadata is preserved and returned with every result.
  - No external dependency is required.
* Each test class is focused on a single behaviour slice.
* Ordering stability is verified explicitly: same query twice → same list.
"""

from __future__ import annotations

import pytest

from hm_arch.storage.vector import (
    LocalVectorStore,
    VectorDocument,
    VectorSearchResult,
    VectorStoreProtocol,
    _token_overlap_score,
    _tokenize,
)


# ---------------------------------------------------------------------------
# Internal scoring helpers (white-box unit tests)
# ---------------------------------------------------------------------------


class TestTokenize:
    def test_lowercase(self) -> None:
        assert _tokenize("Hello World") == ["hello", "world"]

    def test_strips_punctuation(self) -> None:
        assert _tokenize("Python, great!") == ["python", "great"]

    def test_numbers_kept(self) -> None:
        assert "3" in _tokenize("Python 3 is great")

    def test_empty_string(self) -> None:
        assert _tokenize("") == []

    def test_only_punctuation(self) -> None:
        assert _tokenize("!!! ???") == []

    def test_unicode_non_ascii_excluded(self) -> None:
        tokens = _tokenize("café résumé")
        assert "caf" in tokens or "cafe" in tokens or tokens == []


class TestTokenOverlapScore:
    def test_identical_single_token(self) -> None:
        assert _token_overlap_score(["python"], ["python"]) == pytest.approx(1.0)

    def test_no_overlap(self) -> None:
        assert _token_overlap_score(["python"], ["java"]) == pytest.approx(0.0)

    def test_partial_overlap(self) -> None:
        score = _token_overlap_score(["python", "data"], ["python", "science"])
        assert 0.0 < score < 1.0

    def test_empty_query(self) -> None:
        assert _token_overlap_score([], ["python"]) == pytest.approx(0.0)

    def test_empty_doc(self) -> None:
        assert _token_overlap_score(["python"], []) == pytest.approx(0.0)

    def test_both_empty(self) -> None:
        assert _token_overlap_score([], []) == pytest.approx(0.0)

    def test_score_bounded_zero_to_one(self) -> None:
        s = _token_overlap_score(["a", "b", "c"], ["a", "b", "d", "e", "f"])
        assert 0.0 <= s <= 1.0

    def test_more_overlap_higher_score(self) -> None:
        low = _token_overlap_score(["python"], ["java", "coffee"])
        high = _token_overlap_score(["python"], ["python", "is", "great"])
        assert high > low

    def test_repeated_token_counts_once_per_occurrence(self) -> None:
        # query has "python" twice; doc has it once → min(2,1)=1 overlap
        score_repeated = _token_overlap_score(["python", "python"], ["python"])
        # query has "python" once; doc has it once → min(1,1)=1 overlap
        score_single = _token_overlap_score(["python"], ["python"])
        # Both have overlap=1; denominator differs (2 vs 1), so repeated < single
        assert score_repeated < score_single


# ---------------------------------------------------------------------------
# VectorDocument dataclass
# ---------------------------------------------------------------------------


class TestVectorDocument:
    def test_fields_present(self) -> None:
        import dataclasses

        names = {f.name for f in dataclasses.fields(VectorDocument)}
        assert {"id", "text", "metadata"} <= names

    def test_construction_with_metadata(self) -> None:
        doc = VectorDocument(id="d1", text="hello world", metadata={"layer": 2})
        assert doc.id == "d1"
        assert doc.text == "hello world"
        assert doc.metadata == {"layer": 2}

    def test_metadata_defaults_to_empty_dict(self) -> None:
        doc = VectorDocument(id="d2", text="no meta")
        assert doc.metadata == {}

    def test_is_dataclass(self) -> None:
        import dataclasses

        assert dataclasses.is_dataclass(VectorDocument)


# ---------------------------------------------------------------------------
# VectorSearchResult dataclass
# ---------------------------------------------------------------------------


class TestVectorSearchResult:
    def test_fields_present(self) -> None:
        import dataclasses

        names = {f.name for f in dataclasses.fields(VectorSearchResult)}
        assert {"id", "text", "score", "metadata"} <= names

    def test_construction(self) -> None:
        result = VectorSearchResult(
            id="r1", text="some text", score=0.75, metadata={"src": "l2"}
        )
        assert result.id == "r1"
        assert result.score == pytest.approx(0.75)
        assert result.metadata["src"] == "l2"

    def test_metadata_defaults_to_empty_dict(self) -> None:
        result = VectorSearchResult(id="r2", text="text", score=0.5)
        assert result.metadata == {}

    def test_is_dataclass(self) -> None:
        import dataclasses

        assert dataclasses.is_dataclass(VectorSearchResult)


# ---------------------------------------------------------------------------
# VectorStoreProtocol — runtime-checkable
# ---------------------------------------------------------------------------


class TestVectorStoreProtocol:
    def test_local_store_satisfies_protocol(self) -> None:
        store = LocalVectorStore()
        assert isinstance(store, VectorStoreProtocol)

    def test_protocol_is_runtime_checkable(self) -> None:
        # If the protocol were not @runtime_checkable, isinstance() would raise
        # TypeError.  This call must not raise.
        result = isinstance(LocalVectorStore(), VectorStoreProtocol)
        assert result is True

    def test_protocol_requires_upsert(self) -> None:
        assert hasattr(VectorStoreProtocol, "upsert")

    def test_protocol_requires_query(self) -> None:
        assert hasattr(VectorStoreProtocol, "query")

    def test_protocol_requires_delete(self) -> None:
        assert hasattr(VectorStoreProtocol, "delete")

    def test_protocol_requires_clear(self) -> None:
        assert hasattr(VectorStoreProtocol, "clear")


# ---------------------------------------------------------------------------
# LocalVectorStore — basic lifecycle
# ---------------------------------------------------------------------------


class TestLocalVectorStoreBasics:
    def test_empty_on_construction(self) -> None:
        store = LocalVectorStore()
        assert len(store) == 0

    def test_len_increases_on_upsert(self) -> None:
        store = LocalVectorStore()
        store.upsert("a", "alpha text")
        assert len(store) == 1
        store.upsert("b", "beta text")
        assert len(store) == 2

    def test_contains_after_upsert(self) -> None:
        store = LocalVectorStore()
        store.upsert("x", "some text")
        assert "x" in store

    def test_not_contains_before_upsert(self) -> None:
        store = LocalVectorStore()
        assert "x" not in store

    def test_clear_empties_store(self) -> None:
        store = LocalVectorStore()
        store.upsert("a", "alpha")
        store.upsert("b", "beta")
        store.clear()
        assert len(store) == 0

    def test_clear_on_empty_store_is_safe(self) -> None:
        store = LocalVectorStore()
        store.clear()
        assert len(store) == 0


# ---------------------------------------------------------------------------
# Upsert behaviour
# ---------------------------------------------------------------------------


class TestUpsert:
    def test_upsert_inserts_new_document(self) -> None:
        store = LocalVectorStore()
        store.upsert("doc1", "Python programming language")
        assert "doc1" in store

    def test_upsert_replaces_existing_document(self) -> None:
        store = LocalVectorStore()
        store.upsert("doc1", "original text", {"v": 1})
        store.upsert("doc1", "updated text", {"v": 2})
        assert len(store) == 1
        results = store.query("updated")
        assert results[0].text == "updated text"
        assert results[0].metadata["v"] == 2

    def test_upsert_without_metadata(self) -> None:
        store = LocalVectorStore()
        store.upsert("doc1", "some text")
        results = store.query("some")
        assert results[0].metadata == {}

    def test_upsert_with_none_metadata_treated_as_empty(self) -> None:
        store = LocalVectorStore()
        store.upsert("doc1", "some text", None)
        results = store.query("some")
        assert results[0].metadata == {}

    def test_upsert_stores_metadata(self) -> None:
        store = LocalVectorStore()
        store.upsert("doc1", "Python tutorial", {"layer": 2, "source": "L2"})
        results = store.query("Python")
        assert results[0].metadata["layer"] == 2
        assert results[0].metadata["source"] == "L2"

    def test_upsert_does_not_mutate_caller_metadata(self) -> None:
        store = LocalVectorStore()
        meta = {"key": "value"}
        store.upsert("doc1", "text", meta)
        meta["key"] = "changed"
        results = store.query("text")
        assert results[0].metadata["key"] == "value"

    def test_upsert_multiple_documents(self) -> None:
        store = LocalVectorStore()
        for i in range(5):
            store.upsert(f"doc{i}", f"document number {i}")
        assert len(store) == 5


# ---------------------------------------------------------------------------
# Query — relevance ordering (core acceptance criterion)
# ---------------------------------------------------------------------------


class TestQuery:
    def test_query_empty_store_returns_empty(self) -> None:
        store = LocalVectorStore()
        results = store.query("Python")
        assert results == []

    def test_query_returns_list_of_search_results(self) -> None:
        store = LocalVectorStore()
        store.upsert("d1", "Python is fun")
        results = store.query("Python")
        assert isinstance(results, list)
        assert all(isinstance(r, VectorSearchResult) for r in results)

    def test_query_higher_overlap_ranks_first(self) -> None:
        store = LocalVectorStore()
        store.upsert("low", "Java coffee beans enterprise apps")
        store.upsert("high", "Python programming language data science python")
        results = store.query("Python data science")
        assert results[0].id == "high"

    def test_query_exact_match_scores_higher_than_partial(self) -> None:
        store = LocalVectorStore()
        store.upsert("exact", "Python")
        store.upsert("partial", "Python Java Ruby")
        results = store.query("Python")
        assert results[0].id == "exact"

    def test_query_top_k_limits_results(self) -> None:
        store = LocalVectorStore()
        for i in range(10):
            store.upsert(f"doc{i}", f"Python document {i}")
        results = store.query("Python", top_k=3)
        assert len(results) <= 3

    def test_query_top_k_1_returns_single_best(self) -> None:
        store = LocalVectorStore()
        store.upsert("best", "Python data science machine learning")
        store.upsert("worse", "Java enterprise configuration")
        results = store.query("Python data", top_k=1)
        assert len(results) == 1
        assert results[0].id == "best"

    def test_query_top_k_larger_than_store_returns_all(self) -> None:
        store = LocalVectorStore()
        store.upsert("a", "alpha")
        store.upsert("b", "beta")
        results = store.query("alpha", top_k=100)
        assert len(results) == 2

    def test_query_returns_metadata_with_results(self) -> None:
        store = LocalVectorStore()
        store.upsert("d1", "Python tutorial", {"category": "python", "level": "beginner"})
        results = store.query("Python")
        assert results[0].metadata["category"] == "python"
        assert results[0].metadata["level"] == "beginner"

    def test_query_result_metadata_is_copy_not_reference(self) -> None:
        store = LocalVectorStore()
        store.upsert("d1", "Python", {"x": 1})
        r1 = store.query("Python")[0]
        r1.metadata["x"] = 999
        r2 = store.query("Python")[0]
        assert r2.metadata["x"] == 1

    def test_query_score_between_zero_and_one(self) -> None:
        store = LocalVectorStore()
        store.upsert("d1", "Python data science")
        results = store.query("Python")
        assert all(0.0 <= r.score <= 1.0 for r in results)

    def test_query_unrelated_docs_have_zero_score(self) -> None:
        store = LocalVectorStore()
        store.upsert("d1", "zzz yyy xxx completely unrelated")
        results = store.query("Python programming")
        assert results[0].score == pytest.approx(0.0)

    def test_query_preserves_id_and_text(self) -> None:
        store = LocalVectorStore()
        store.upsert("my-id", "unique text content here")
        results = store.query("unique text")
        assert results[0].id == "my-id"
        assert results[0].text == "unique text content here"

    def test_query_descending_score_order(self) -> None:
        store = LocalVectorStore()
        store.upsert("a", "Python")
        store.upsert("b", "Python programming")
        store.upsert("c", "Python programming language tutorial")
        results = store.query("Python programming language tutorial")
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_query_default_top_k_is_10(self) -> None:
        store = LocalVectorStore()
        for i in range(15):
            store.upsert(f"doc{i}", f"Python {i}")
        results = store.query("Python")
        assert len(results) <= 10


# ---------------------------------------------------------------------------
# Query stability — same query always returns same ordered result
# ---------------------------------------------------------------------------


class TestQueryStability:
    def test_repeated_query_returns_identical_results(self) -> None:
        store = LocalVectorStore()
        store.upsert("a", "Python data science")
        store.upsert("b", "Java enterprise apps")
        store.upsert("c", "Python web framework")

        first = [(r.id, r.score) for r in store.query("Python")]
        second = [(r.id, r.score) for r in store.query("Python")]
        assert first == second

    def test_ordering_is_deterministic_across_upsert_order(self) -> None:
        """Documents with equal content but different insertion order."""
        store_a = LocalVectorStore()
        store_a.upsert("x", "Python")
        store_a.upsert("y", "Python")

        store_b = LocalVectorStore()
        store_b.upsert("y", "Python")
        store_b.upsert("x", "Python")

        ids_a = [r.id for r in store_a.query("Python")]
        ids_b = [r.id for r in store_b.query("Python")]
        # Both stores should return the same stable order (x before y due to id tiebreak)
        assert ids_a == ids_b

    def test_tiebreak_by_id_ascending(self) -> None:
        store = LocalVectorStore()
        store.upsert("z-doc", "Python")
        store.upsert("a-doc", "Python")
        store.upsert("m-doc", "Python")
        results = store.query("Python")
        ids = [r.id for r in results]
        assert ids == sorted(ids)

    def test_multi_query_ordering_consistent(self) -> None:
        store = LocalVectorStore()
        store.upsert("best", "Python machine learning data science")
        store.upsert("good", "Python scripting automation")
        store.upsert("weak", "Java C++ Rust")

        for _ in range(3):
            results = store.query("Python data")
            assert results[0].id == "best"


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestDelete:
    def test_delete_returns_true_for_existing_document(self) -> None:
        store = LocalVectorStore()
        store.upsert("d1", "Python")
        assert store.delete("d1") is True

    def test_delete_returns_false_for_missing_document(self) -> None:
        store = LocalVectorStore()
        assert store.delete("nonexistent") is False

    def test_delete_removes_document_from_store(self) -> None:
        store = LocalVectorStore()
        store.upsert("d1", "Python")
        store.delete("d1")
        assert "d1" not in store
        assert len(store) == 0

    def test_delete_only_removes_targeted_document(self) -> None:
        store = LocalVectorStore()
        store.upsert("d1", "Python")
        store.upsert("d2", "Java")
        store.delete("d1")
        assert "d2" in store
        assert len(store) == 1

    def test_deleted_document_absent_from_query(self) -> None:
        store = LocalVectorStore()
        store.upsert("d1", "Python programming")
        store.upsert("d2", "Python web")
        store.delete("d1")
        results = store.query("Python")
        ids = [r.id for r in results]
        assert "d1" not in ids
        assert "d2" in ids

    def test_delete_then_re_upsert(self) -> None:
        store = LocalVectorStore()
        store.upsert("d1", "original")
        store.delete("d1")
        store.upsert("d1", "new text")
        results = store.query("new")
        assert results[0].id == "d1"
        assert results[0].text == "new text"

    def test_double_delete_returns_false_second_time(self) -> None:
        store = LocalVectorStore()
        store.upsert("d1", "text")
        store.delete("d1")
        assert store.delete("d1") is False

    def test_delete_empty_store_returns_false(self) -> None:
        store = LocalVectorStore()
        assert store.delete("any") is False


# ---------------------------------------------------------------------------
# Metadata filter
# ---------------------------------------------------------------------------


class TestMetadataFilter:
    def _store_with_layers(self) -> LocalVectorStore:
        store = LocalVectorStore()
        store.upsert("ep1", "Python episode memory", {"layer": 2, "type": "episode"})
        store.upsert("ep2", "Java episode memory", {"layer": 2, "type": "episode"})
        store.upsert("sem1", "Python semantic fact", {"layer": 3, "type": "semantic"})
        store.upsert("no_meta", "Python untagged")
        return store

    def test_filter_by_single_key(self) -> None:
        store = self._store_with_layers()
        results = store.query("Python", metadata_filter={"layer": 3})
        ids = {r.id for r in results}
        assert "sem1" in ids
        assert "ep1" not in ids
        assert "ep2" not in ids
        assert "no_meta" not in ids

    def test_filter_by_multiple_keys(self) -> None:
        store = self._store_with_layers()
        results = store.query("Python", metadata_filter={"layer": 2, "type": "episode"})
        ids = {r.id for r in results}
        assert "ep1" in ids
        assert "ep2" in ids
        assert "sem1" not in ids

    def test_filter_no_match_returns_empty(self) -> None:
        store = self._store_with_layers()
        results = store.query("Python", metadata_filter={"layer": 99})
        assert results == []

    def test_no_filter_returns_all_candidates(self) -> None:
        store = self._store_with_layers()
        results = store.query("Python memory")
        ids = {r.id for r in results}
        assert {"ep1", "ep2", "sem1"}.issubset(ids)

    def test_filter_none_behaves_like_no_filter(self) -> None:
        store = self._store_with_layers()
        with_none = store.query("Python", metadata_filter=None)
        without = store.query("Python")
        assert [r.id for r in with_none] == [r.id for r in without]

    def test_filter_by_string_value(self) -> None:
        store = LocalVectorStore()
        store.upsert("a", "text one", {"category": "alpha"})
        store.upsert("b", "text two", {"category": "beta"})
        results = store.query("text", metadata_filter={"category": "alpha"})
        ids = {r.id for r in results}
        assert "a" in ids
        assert "b" not in ids

    def test_filter_partial_key_match_excluded(self) -> None:
        """A document missing one of the required filter keys is excluded."""
        store = LocalVectorStore()
        store.upsert("full", "text", {"a": 1, "b": 2})
        store.upsert("partial", "text", {"a": 1})
        results = store.query("text", metadata_filter={"a": 1, "b": 2})
        ids = {r.id for r in results}
        assert "full" in ids
        assert "partial" not in ids


# ---------------------------------------------------------------------------
# Importability from hm_arch.storage package
# ---------------------------------------------------------------------------


def test_importable_from_storage_package() -> None:
    from hm_arch.storage import (
        LocalVectorStore as LVS,
        VectorDocument as VD,
        VectorSearchResult as VSR,
        VectorStoreProtocol as VSP,
    )

    assert LVS is LocalVectorStore
    assert VD is VectorDocument
    assert VSR is VectorSearchResult
    assert VSP is VectorStoreProtocol


def test_importable_directly_from_vector_module() -> None:
    from hm_arch.storage.vector import (
        LocalVectorStore as LVS,
        VectorDocument as VD,
        VectorSearchResult as VSR,
        VectorStoreProtocol as VSP,
    )

    assert LVS is LocalVectorStore
    assert VD is VectorDocument
    assert VSR is VectorSearchResult
    assert VSP is VectorStoreProtocol


def test_storage_package_all_includes_vector_names() -> None:
    import hm_arch.storage as storage

    for name in ("LocalVectorStore", "VectorDocument", "VectorSearchResult", "VectorStoreProtocol"):
        assert name in storage.__all__, f"{name} missing from hm_arch.storage.__all__"


# ---------------------------------------------------------------------------
# End-to-end: upsert → query → delete workflow
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_full_workflow(self) -> None:
        store = LocalVectorStore()

        # Upsert three documents
        store.upsert("p1", "Python is great for data science", {"lang": "python"})
        store.upsert("p2", "Python web frameworks Django Flask", {"lang": "python"})
        store.upsert("j1", "Java enterprise Spring Boot", {"lang": "java"})

        # Query — Python-related docs should rank above Java
        results = store.query("Python data science web", top_k=3)
        assert len(results) == 3
        assert results[0].id in {"p1", "p2"}
        assert results[-1].id == "j1"

        # Metadata preserved
        python_results = [r for r in results if r.metadata.get("lang") == "python"]
        assert len(python_results) == 2

        # Delete one Python doc
        assert store.delete("p1") is True
        assert len(store) == 2

        # Deleted doc no longer returned
        results_after = store.query("Python data science web", top_k=3)
        assert all(r.id != "p1" for r in results_after)

        # Clear
        store.clear()
        assert len(store) == 0
        assert store.query("Python") == []

    def test_metadata_filter_narrows_results(self) -> None:
        store = LocalVectorStore()
        store.upsert("e1", "Python programming", {"layer": 2})
        store.upsert("e2", "Python machine learning", {"layer": 2})
        store.upsert("s1", "Python semantic triple", {"layer": 3})

        l2_results = store.query("Python", metadata_filter={"layer": 2})
        assert {r.id for r in l2_results} == {"e1", "e2"}

        l3_results = store.query("Python", metadata_filter={"layer": 3})
        assert {r.id for r in l3_results} == {"s1"}

    def test_ordering_stability_after_multiple_upserts(self) -> None:
        store = LocalVectorStore()
        store.upsert("low", "the quick brown fox")
        store.upsert("high", "Python data science machine learning Python")

        run1 = [r.id for r in store.query("Python data science")]
        run2 = [r.id for r in store.query("Python data science")]
        assert run1 == run2
        assert run1[0] == "high"
