"""Storage sub-package for HM-Arch.

Exposes the SQLite backend and the vector store abstraction (local fallback
plus optional ChromaDB).  Import :mod:`hm_arch.storage.chroma` only when the
optional ``chromadb`` dependency is installed.
"""

from hm_arch.storage.sqlite import SQLiteStore
from hm_arch.storage.vector import (
    LocalVectorStore,
    VectorDocument,
    VectorSearchResult,
    VectorStoreProtocol,
)

__all__ = [
    "SQLiteStore",
    "LocalVectorStore",
    "VectorDocument",
    "VectorSearchResult",
    "VectorStoreProtocol",
    "ChromaVectorStore",
]


def __getattr__(name: str):
    if name == "ChromaVectorStore":
        from hm_arch.storage.chroma import ChromaVectorStore

        return ChromaVectorStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
