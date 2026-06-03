"""Configuration object and built-in presets for HM-Arch.

Field names follow the PRD contract so that later implementation modules
(decay, retrieval, consolidation) can read config values by canonical name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

_VALID_PRESETS = {"code_agent", "chat_agent", "research_agent"}


@dataclass
class MemoryConfig:
    """Runtime configuration for an :class:`HMArch` instance.

    Time constants are expressed in hours, matching the PRD formulas.
    """

    # -------------------------------------------------------------------
    # Database / filesystem
    # -------------------------------------------------------------------
    db_path: str = "./.agent_memory.db"
    archive_root: Optional[str] = None
    """Root directory for L4 gzip archives.  When ``None``, derived from
    ``db_path`` (parent of the database file, or ``./.agent_memory_data`` for
    ``":memory:"``)."""

    # -------------------------------------------------------------------
    # Decay - L2 bi-exponential, hours
    # -------------------------------------------------------------------
    l2_fast_tau: float = 24.0
    """Fast-decay time constant in hours."""
    l2_slow_tau: float = 720.0
    """Slow-decay time constant in hours."""
    l2_fast_weight: float = 0.30
    """Fraction of strength governed by the fast component (0–1)."""

    # -------------------------------------------------------------------
    # Decay - L3 power-law, hours
    # -------------------------------------------------------------------
    l3_tau: float = 168.0
    """Scale parameter in hours for the L3 power-law decay."""
    l3_beta: float = 0.30
    """Exponent for the L3 power-law decay (larger = faster forgetting)."""

    # -------------------------------------------------------------------
    # ASM-2 review scheduling
    # -------------------------------------------------------------------
    initial_ef: float = 2.5
    """Initial ease factor for new memories (SM-2 default)."""
    min_ef: float = 1.3
    """Minimum ease factor (SM-2 floor)."""
    review_trigger_retention: float = 0.50
    """Retention level below which a review is scheduled."""

    # -------------------------------------------------------------------
    # Archive / delete thresholds
    # -------------------------------------------------------------------
    l2_archive_threshold: float = 0.15
    """L2 retention below which an episodic memory is compressed to L4."""
    l2_delete_threshold: float = 0.05
    """L2 retention below which an episodic memory is marked deletable."""
    l3_archive_threshold: float = 0.30
    """L3 retention below which a semantic memory is eligible for archiving."""
    l3_delete_threshold: float = 0.10
    """L3 retention below which a semantic memory is marked deletable."""
    redundancy_threshold: float = 0.85
    """Cosine-similarity above which two memories are considered duplicates."""

    # -------------------------------------------------------------------
    # Consolidation
    # -------------------------------------------------------------------
    auto_consolidate: bool = True
    """Whether consolidation runs automatically in the background."""
    consolidate_interval_hours: int = 24
    """Hours between automatic consolidation cycles."""
    deletion_safety_period_hours: int = 168
    """Hours a memory must remain ``deletable`` before physical cleanup."""
    forgetting_score_threshold: float = 0.35
    """Minimum PRD context-aware forgetting score required for automated removal."""
    replay_sample_ratio: float = 0.20
    """Fraction of eligible L2 episodes replayed per consolidation cycle."""

    # -------------------------------------------------------------------
    # Memory strength modulation (HM-29)
    # -------------------------------------------------------------------
    strength_min: float = 0.2
    """Lower bound for ``initial_strength`` after PRD modulation."""
    strength_max: float = 6.75
    """Upper bound for ``initial_strength`` (``0.5×2×1.5×3×1.5`` PRD product)."""
    retrieval_reinforcement_increment: float = 0.3
    """``R_mod`` increment per successful retrieval (PRD: ``+0.3``)."""
    retrieval_relevance_threshold: float = 0.25
    """Minimum query relevance required to count as a successful retrieval."""

    # -------------------------------------------------------------------
    # In-memory layer caps
    # -------------------------------------------------------------------
    l0_capacity: int = 7
    """Maximum items in the L0 sensory register (FIFO eviction)."""

    # -------------------------------------------------------------------
    # Storage caps
    # -------------------------------------------------------------------
    max_memories_l2: int = 100000
    """Maximum number of episodes stored in the L2 episodic buffer."""
    max_memories_l3: int = 50000
    """Maximum number of triples stored in L3 semantic memory."""
    max_skills_l5: int = 10000
    """Maximum number of skill records stored in L5 procedural memory."""

    # -------------------------------------------------------------------
    # LLM / embedding providers (opt-in; local fallback is default)
    # -------------------------------------------------------------------
    enable_llm_providers: bool = False
    """When ``True``, use configured remote providers for importance and extraction."""
    provider_fallback_to_local: bool = True
    """Fall back to local heuristics when API keys or optional deps are missing."""
    llm_provider: str = "local"
    """LLM provider identifier: ``"local"``, ``"deepseek"``, or ``"openai"``."""
    llm_model: str = "deepseek-chat"
    """Model name used for importance scoring and semantic extraction."""
    llm_api_key: Optional[str] = None
    """Optional API key. ``None`` means provider code should read environment variables."""
    llm_base_url: Optional[str] = None
    """Optional provider base URL override."""
    embedding_provider: str = "local"
    """Embedding provider identifier: ``"local"``, ``"deepseek"``, or ``"openai"``."""
    embedding_model: str = "text-embedding-3-small"
    """Model name for embedding generation."""
    embedding_dim: int = 384
    """Embedding dimensionality expected by the configured provider."""
    vector_backend: str = "local"
    """Vector store backend: ``"local"`` (token overlap) or ``"chroma"``."""
    chroma_persist_directory: Optional[str] = None
    """Directory for ChromaDB persistence.  Derived from ``db_path`` when ``None``."""
    chroma_collection_prefix: str = "hm_arch"
    """Prefix for Chroma collection names (episodic/semantic suffixes are appended)."""

    # -------------------------------------------------------------------
    # Retrieval
    # -------------------------------------------------------------------
    layer_priorities: dict[str, float] = field(
        default_factory=lambda: {
            "L0": 1.0,
            "L1": 0.9,
            "L2": 0.7,
            "L3": 0.8,
            "L4": 0.5,
        }
    )
    """Per-layer multipliers applied when computing the final ranking score."""

    @classmethod
    def preset(cls, name: str) -> "MemoryConfig":
        """Return a :class:`MemoryConfig` tuned for a specific agent type.

        Parameters
        ----------
        name:
            One of ``"code_agent"``, ``"chat_agent"``, or
            ``"research_agent"``.

        Raises
        ------
        ValueError
            When *name* is not a known preset.
        """
        if name not in _VALID_PRESETS:
            raise ValueError(
                f"Unknown preset {name!r}.  "
                f"Valid presets are: {sorted(_VALID_PRESETS)}"
            )

        if name == "code_agent":
            return cls(
                l2_fast_tau=18.0,
                l2_slow_tau=480.0,
                l2_fast_weight=0.35,
                l3_tau=120.0,
                l3_beta=0.35,
                initial_ef=2.5,
                min_ef=1.3,
                review_trigger_retention=0.50,
                l2_archive_threshold=0.15,
                l2_delete_threshold=0.05,
                l3_archive_threshold=0.30,
                l3_delete_threshold=0.10,
                redundancy_threshold=0.85,
                auto_consolidate=True,
                consolidate_interval_hours=12,
                replay_sample_ratio=0.20,
                layer_priorities={
                    "L0": 1.0,
                    "L1": 0.95,
                    "L2": 0.75,
                    "L3": 0.85,
                    "L4": 0.5,
                },
            )

        if name == "chat_agent":
            return cls(
                l2_fast_tau=30.0,
                l2_slow_tau=1000.0,
                l2_fast_weight=0.30,
                l3_tau=240.0,
                l3_beta=0.25,
                initial_ef=2.5,
                min_ef=1.3,
                review_trigger_retention=0.50,
                l2_archive_threshold=0.15,
                l2_delete_threshold=0.05,
                l3_archive_threshold=0.30,
                l3_delete_threshold=0.10,
                redundancy_threshold=0.85,
                auto_consolidate=True,
                consolidate_interval_hours=24,
                replay_sample_ratio=0.20,
                layer_priorities={
                    "L0": 1.0,
                    "L1": 1.0,
                    "L2": 0.65,
                    "L3": 0.75,
                    "L4": 0.5,
                },
            )

        # research_agent
        return cls(
            l2_fast_tau=6.0,
            l2_slow_tau=200.0,
            l2_fast_weight=0.30,
            l3_tau=720.0,
            l3_beta=0.15,
            initial_ef=2.8,
            min_ef=1.3,
            review_trigger_retention=0.50,
            l2_archive_threshold=0.15,
            l2_delete_threshold=0.05,
            l3_archive_threshold=0.30,
            l3_delete_threshold=0.10,
            redundancy_threshold=0.85,
            auto_consolidate=True,
            consolidate_interval_hours=6,
            replay_sample_ratio=0.20,
            layer_priorities={
                "L0": 1.0,
                "L1": 0.85,
                "L2": 0.80,
                "L3": 0.95,
                "L4": 0.5,
            },
        )
