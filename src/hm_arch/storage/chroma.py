"""Optional ChromaDB vector store behind :class:`~hm_arch.storage.vector.VectorStoreProtocol`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hm_arch.storage.vector import VectorSearchResult

if TYPE_CHECKING:
    from hm_arch.providers.protocol import EmbeddingProviderProtocol


class ChromaVectorStore:
    """Persistent ChromaDB collection with pluggable embeddings.

    Requires the optional ``chromadb`` package.  Offline tests should mock
    ``chromadb`` or inject a :class:`~hm_arch.storage.vector.LocalVectorStore`.
    """

    def __init__(
        self,
        *,
        persist_directory: str,
        collection_name: str,
        embedding_provider: EmbeddingProviderProtocol,
    ) -> None:
        try:
            import chromadb  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "chromadb is not installed. HM-Arch is not on PyPI. "
                "Install with pip install 'chromadb>=0.5.0', from source pip install -e '.[chroma]', "
                "or add the [chroma] extra when installing a release wheel "
                "(e.g. pip install '/path/to/hm_arch-*.whl[chroma]')."
            ) from exc

        self._embedding = embedding_provider
        self._client = chromadb.PersistentClient(path=persist_directory)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(self, id: str, text: str, metadata: dict | None = None) -> None:
        meta = dict(metadata) if metadata is not None else {}
        vectors = self._embedding.embed([text])
        self._collection.upsert(
            ids=[id],
            documents=[text],
            metadatas=[meta],
            embeddings=vectors,
        )

    def query(
        self,
        text: str,
        top_k: int = 10,
        metadata_filter: dict | None = None,
    ) -> list[VectorSearchResult]:
        where = metadata_filter if metadata_filter else None
        query_embedding = self._embedding.embed([text])[0]
        raw = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
        )
        return _parse_chroma_results(raw)

    def delete(self, id: str) -> bool:
        try:
            existing = self._collection.get(ids=[id])
            if not existing["ids"]:
                return False
            self._collection.delete(ids=[id])
            return True
        except Exception:
            return False

    def clear(self) -> None:
        name = self._collection.name
        self._client.delete_collection(name)
        self._collection = self._client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )


def _parse_chroma_results(raw: dict) -> list[VectorSearchResult]:
    ids = (raw.get("ids") or [[]])[0]
    documents = (raw.get("documents") or [[]])[0]
    metadatas = (raw.get("metadatas") or [[]])[0]
    distances = (raw.get("distances") or [[]])[0]

    results: list[VectorSearchResult] = []
    for idx, doc_id in enumerate(ids):
        text = documents[idx] if idx < len(documents) else ""
        meta = metadatas[idx] if idx < len(metadatas) else {}
        if meta is None:
            meta = {}
        distance = distances[idx] if idx < len(distances) else 1.0
        score = max(0.0, min(1.0, 1.0 - float(distance)))
        results.append(
            VectorSearchResult(
                id=doc_id,
                text=text or "",
                score=score,
                metadata=dict(meta),
            )
        )

    results.sort(key=lambda r: (-r.score, r.id))
    return results
