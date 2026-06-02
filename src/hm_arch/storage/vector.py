"""Vector store abstraction and deterministic local fallback for HM-Arch.

Provides:

* :class:`VectorDocument` — lightweight dataclass for stored documents.
* :class:`VectorSearchResult` — dataclass returned by :meth:`LocalVectorStore.query`.
* :class:`VectorStoreProtocol` — structural :class:`~typing.Protocol` that
  every backend (local fallback, future ChromaDB adapter, …) must satisfy.
* :class:`LocalVectorStore` — in-process, stdlib-only, fully deterministic
  implementation suitable for offline tests and demos.

No external dependencies are required.  The local store uses a
token-overlap scoring strategy: both the query and each stored document are
lowercased and split into alphanumeric tokens; relevance is the fraction of
query-token occurrences matched in the document.  Ties are broken by document
id (ascending) so that query results are **stable across repeated calls on
the same store contents**.

Design notes
------------
* The protocol is marked :func:`~typing.runtime_checkable` so
  ``isinstance(store, VectorStoreProtocol)`` works in tests.
* :class:`LocalVectorStore` intentionally uses only ``re``, ``dataclasses``,
  and ``typing`` from the standard library.
* Thread-safety is *not* guaranteed; callers must synchronise if needed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------

__all__ = [
    "VectorDocument",
    "VectorSearchResult",
    "VectorStoreProtocol",
    "LocalVectorStore",
]


@dataclass
class VectorDocument:
    """A single document held inside a vector store.

    Parameters
    ----------
    id:
        Caller-controlled string key.  Must be unique within a store;
        upserting with an existing id replaces the previous entry.
    text:
        The raw text content that is indexed for similarity search.
    metadata:
        Arbitrary key/value pairs attached to this document.  Returned
        verbatim with every :class:`VectorSearchResult`.
    """

    id: str
    text: str
    metadata: dict = field(default_factory=dict)


@dataclass
class VectorSearchResult:
    """A single hit returned by :meth:`LocalVectorStore.query`.

    Parameters
    ----------
    id:
        The id of the matching document.
    text:
        The stored text of the matching document.
    score:
        Relevance score in ``[0.0, 1.0]``.  Higher is more relevant.
    metadata:
        A shallow copy of the document's metadata dict.
    """

    id: str
    text: str
    score: float
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Protocol — structural interface for all backends
# ---------------------------------------------------------------------------


@runtime_checkable
class VectorStoreProtocol(Protocol):
    """Structural interface that every vector store backend must satisfy.

    Marking this :func:`~typing.runtime_checkable` lets tests use
    ``isinstance(obj, VectorStoreProtocol)`` to verify conformance without
    inheriting from a concrete base class.
    """

    def upsert(self, id: str, text: str, metadata: dict | None = None) -> None:
        """Insert or replace a document identified by *id*."""
        ...

    def query(
        self,
        text: str,
        top_k: int = 10,
        metadata_filter: dict | None = None,
    ) -> list[VectorSearchResult]:
        """Return up to *top_k* results most relevant to *text*."""
        ...

    def delete(self, id: str) -> bool:
        """Delete document *id*.  Returns ``True`` if it existed."""
        ...

    def clear(self) -> None:
        """Remove every document from the store."""
        ...


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Return a list of lowercase alphanumeric tokens extracted from *text*."""
    return _TOKEN_RE.findall(text.lower())


def _token_overlap_score(query_tokens: list[str], doc_tokens: list[str]) -> float:
    """Compute a deterministic relevance score via token-frequency overlap.

    Algorithm
    ---------
    1. Build term-frequency maps for the query and the document.
    2. For each unique query token, accumulate
       ``min(query_tf[t], doc_tf[t])`` (zero if the token is absent from
       the document).
    3. Normalise by ``max(len(query_tokens), len(doc_tokens))`` so the score
       stays in ``[0.0, 1.0]``.

    Returns ``0.0`` when either token list is empty.
    """
    if not query_tokens or not doc_tokens:
        return 0.0

    query_tf: dict[str, int] = {}
    for t in query_tokens:
        query_tf[t] = query_tf.get(t, 0) + 1

    doc_tf: dict[str, int] = {}
    for t in doc_tokens:
        doc_tf[t] = doc_tf.get(t, 0) + 1

    overlap = sum(min(cnt, doc_tf.get(tok, 0)) for tok, cnt in query_tf.items())
    denom = max(len(query_tokens), len(doc_tokens))
    return overlap / denom


# ---------------------------------------------------------------------------
# Local deterministic fallback
# ---------------------------------------------------------------------------


class LocalVectorStore:
    """In-memory, stdlib-only, deterministic vector store.

    This implementation is the default fallback for offline tests and demos.
    It requires no external API keys, no ChromaDB installation, and no network
    access.

    Scoring is entirely token-based (see :func:`_token_overlap_score`).
    Given identical store contents, the same query always produces the same
    result list in the same order — primary sort key is score descending,
    secondary sort key is document id ascending.

    Examples
    --------
    ::

        store = LocalVectorStore()
        store.upsert("doc1", "Python is great for data science")
        store.upsert("doc2", "Java is used for enterprise apps")
        results = store.query("Python data", top_k=2)
        assert results[0].id == "doc1"
    """

    def __init__(self) -> None:
        self._docs: dict[str, VectorDocument] = {}

    # ------------------------------------------------------------------
    # VectorStoreProtocol implementation
    # ------------------------------------------------------------------

    def upsert(self, id: str, text: str, metadata: dict | None = None) -> None:
        """Insert or replace the document with the given *id*.

        Parameters
        ----------
        id:
            Unique document identifier.
        text:
            The text content to index.
        metadata:
            Optional key/value pairs stored alongside the document.
            Defaults to an empty dict when ``None``.
        """
        self._docs[id] = VectorDocument(
            id=id,
            text=text,
            metadata=dict(metadata) if metadata is not None else {},
        )

    def query(
        self,
        text: str,
        top_k: int = 10,
        metadata_filter: dict | None = None,
    ) -> list[VectorSearchResult]:
        """Return up to *top_k* documents most relevant to *text*.

        Parameters
        ----------
        text:
            The query string.
        top_k:
            Maximum number of results to return.  If fewer documents match
            the optional filter, fewer results are returned.
        metadata_filter:
            When provided, only documents whose ``metadata`` contains **all**
            key/value pairs in this dict are considered.  Comparison is by
            equality (``==``).

        Returns
        -------
        list[VectorSearchResult]
            Results sorted by score descending; ties broken by id ascending.
            Each result carries a shallow copy of the stored metadata so that
            mutations by callers do not affect stored state.
        """
        query_tokens = _tokenize(text)

        results: list[VectorSearchResult] = []
        for doc in self._docs.values():
            if metadata_filter is not None:
                if not all(doc.metadata.get(k) == v for k, v in metadata_filter.items()):
                    continue

            doc_tokens = _tokenize(doc.text)
            score = _token_overlap_score(query_tokens, doc_tokens)
            results.append(
                VectorSearchResult(
                    id=doc.id,
                    text=doc.text,
                    score=score,
                    metadata=dict(doc.metadata),
                )
            )

        # Primary: score descending.  Secondary: id ascending (stable tiebreak).
        results.sort(key=lambda r: (-r.score, r.id))
        return results[:top_k]

    def delete(self, id: str) -> bool:
        """Remove the document with *id* from the store.

        Returns
        -------
        bool
            ``True`` if the document existed and was removed; ``False`` if
            no document with that id was found.
        """
        if id in self._docs:
            del self._docs[id]
            return True
        return False

    def clear(self) -> None:
        """Remove every document from the store."""
        self._docs.clear()

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        """Return the number of documents currently in the store."""
        return len(self._docs)

    def __contains__(self, id: object) -> bool:
        """Support ``id in store`` membership tests."""
        return id in self._docs
