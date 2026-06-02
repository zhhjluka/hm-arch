"""Configuration objects for the HM-Arch SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass(slots=True)
class MemoryConfig:
    """Runtime configuration for local HM-Arch memory behavior."""

    db_path: str = ".agent_memory.db"
    l0_capacity: int = 128
    l1_capacity: int = 512
    default_top_k: int = 5
    consolidation_batch_size: int = 50
    retention_threshold: float = 0.25
    importance_threshold: float = 0.5
    vector_backend: str = "local"
    llm_provider: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    _PRESETS: ClassVar[dict[str, dict[str, Any]]] = {
        "code_agent": {
            "l0_capacity": 256,
            "l1_capacity": 1024,
            "default_top_k": 8,
            "consolidation_batch_size": 100,
            "retention_threshold": 0.2,
            "importance_threshold": 0.45,
        },
        "chat_agent": {
            "l0_capacity": 128,
            "l1_capacity": 512,
            "default_top_k": 5,
            "consolidation_batch_size": 50,
            "retention_threshold": 0.3,
            "importance_threshold": 0.4,
        },
        "research_agent": {
            "l0_capacity": 384,
            "l1_capacity": 1536,
            "default_top_k": 10,
            "consolidation_batch_size": 150,
            "retention_threshold": 0.18,
            "importance_threshold": 0.6,
        },
    }

    @classmethod
    def preset(cls, name: str) -> "MemoryConfig":
        """Return a named local/offline configuration preset."""

        normalized_name = name.strip().lower()
        try:
            values = cls._PRESETS[normalized_name]
        except KeyError as exc:
            valid = ", ".join(sorted(cls._PRESETS))
            raise ValueError(
                f"Unknown memory config preset {name!r}. Valid presets: {valid}."
            ) from exc

        return cls(**values, metadata={"preset": normalized_name})
