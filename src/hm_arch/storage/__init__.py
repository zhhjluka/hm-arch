"""Storage sub-package for HM-Arch.

Currently exposes only the SQLite backend. Future sub-modules (vector store,
cache) will be added here without changing the public API of existing modules.
"""

from hm_arch.storage.sqlite import SQLiteStore

__all__ = ["SQLiteStore"]
