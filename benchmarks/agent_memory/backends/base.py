"""Shared lifecycle helpers for benchmark memory backends."""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from ..compatibility import assert_supported
from ..contract import (
    ConsolidateResult,
    IngestResult,
    IngestTurn,
    MemoryBackendRunConfig,
    MemoryProviderId,
    RecallResult,
)


class BaseMemoryBackend(ABC):
    """Common setup/teardown and metric recording for benchmark backends."""

    provider_id: MemoryProviderId

    def __init__(self, config: MemoryBackendRunConfig) -> None:
        assert_supported(config.provider_id, config.agent_id)
        if config.provider_id is not self.provider_id:
            raise ValueError(
                f"config provider {config.provider_id.value!r} does not match "
                f"backend {self.provider_id.value!r}"
            )
        self.config = config
        self.agent_id = config.agent_id
        self._ready = False

    def setup(self) -> None:
        """Create an isolated namespace and initialize provider state."""
        self.storage_dir().mkdir(parents=True, exist_ok=True)
        self._setup_provider()
        self._ready = True

    def reset(self) -> None:
        """Drop provider state and re-create an isolated namespace."""
        self.teardown()
        self.setup()

    def teardown(self) -> None:
        """Release provider resources and remove isolated storage."""
        self._teardown_provider()
        storage = self.storage_dir()
        if storage.exists():
            shutil.rmtree(storage, ignore_errors=True)
        self._ready = False

    def storage_dir(self) -> Path:
        return self.config.storage_dir()

    @abstractmethod
    def _setup_provider(self) -> None:
        """Initialize provider-specific state after the namespace exists."""

    @abstractmethod
    def _teardown_provider(self) -> None:
        """Release provider-specific resources."""

    @abstractmethod
    def ingest(self, turn: IngestTurn) -> IngestResult:
        """Persist one normalized conversation turn."""

    @abstractmethod
    def recall(self, query: str, *, top_k: int | None = None) -> RecallResult:
        """Retrieve provider context for a benchmark query."""

    @abstractmethod
    def consolidate(self) -> ConsolidateResult:
        """Run provider-side consolidation when supported."""

    def _require_ready(self) -> None:
        if not self._ready:
            raise RuntimeError(
                f"{self.provider_id.value} backend is not set up; call setup() first"
            )
