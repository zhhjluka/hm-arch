"""Storage sub-package for HM-Arch.

Exposes the SQLite backend and the vector store abstraction (local fallback
plus the structural protocol).  Future backends (ChromaDB, etc.) can be added
without changing the public API of existing modules.
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
]
