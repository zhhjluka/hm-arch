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

    Decay parameters
    ----------------
    L2 episodic buffer uses a bi-exponential model:

    .. code-block:: text

        R_L2(t) = l2_fast_weight * exp(-t / l2_fast_tau)
                + (1 - l2_fast_weight) * exp(-t / l2_slow_tau)

    L3 semantic memory uses a power-law model:

    .. code-block:: text

        R_L3(t) = (1 + t / l3_tau) ** (-l3_beta)

    Storage caps
    ------------
    Layer capacities are enforced as item counts.  When a layer exceeds its
    cap, the lowest-retention items are evicted or promoted to the next layer.

    ASM-2 scheduling
    ----------------
    ``initial_ef`` and ``min_ef`` follow the standard SM-2 / ASM-2 constants.
    """

    # -------------------------------------------------------------------
    # Database
    # -------------------------------------------------------------------
    db_path: str = "./.agent_memory.db"

    # -------------------------------------------------------------------
    # Decay — L2 bi-exponential
    # -------------------------------------------------------------------
    l2_fast_tau: float = 2.0
    """Fast-decay time constant in days (controls short-term forgetting)."""
    l2_slow_tau: float = 28.0
    """Slow-decay time constant in days (controls long-term forgetting)."""
    l2_fast_weight: float = 0.40
    """Fraction of strength governed by the fast component (0–1)."""

    # -------------------------------------------------------------------
    # Decay — L3 power-law
    # -------------------------------------------------------------------
    l3_tau: float = 10.0
    """Scale parameter in days for the L3 power-law decay."""
    l3_beta: float = 0.30
    """Exponent for the L3 power-law decay (larger = faster forgetting)."""

    # -------------------------------------------------------------------
    # ASM-2 review scheduling
    # -------------------------------------------------------------------
    initial_ef: float = 2.5
    """Initial ease factor for new memories (SM-2 default)."""
    min_ef: float = 1.3
    """Minimum ease factor (SM-2 floor)."""
    review_trigger_retention: float = 0.70
    """Retention level below which a review is scheduled."""

    # -------------------------------------------------------------------
    # Archive / delete thresholds
    # -------------------------------------------------------------------
    archive_threshold: float = 0.30
    """Retention level below which an L2 memory is promoted to L4 archive."""
    delete_threshold: float = 0.10
    """Retention level below which a memory is marked deletable."""
    redundancy_threshold: float = 0.92
    """Cosine-similarity above which two memories are considered duplicates."""

    # -------------------------------------------------------------------
    # Consolidation
    # -------------------------------------------------------------------
    auto_consolidate: bool = True
    """Whether consolidation runs automatically in the background."""
    consolidate_interval_hours: float = 1.0
    """Hours between automatic consolidation cycles."""
    replay_sample_ratio: float = 0.20
    """Fraction of eligible L2 episodes replayed per consolidation cycle."""

    # -------------------------------------------------------------------
    # Storage caps
    # -------------------------------------------------------------------
    max_memories_l2: int = 500
    """Maximum number of episodes stored in the L2 episodic buffer."""
    max_memories_l3: int = 2000
    """Maximum number of triples stored in L3 semantic memory."""
    max_skills_l5: int = 200
    """Maximum number of skill records stored in L5 procedural memory."""

    # -------------------------------------------------------------------
    # LLM / embedding providers (optional — None = local fallback)
    # -------------------------------------------------------------------
    embedding_provider: Optional[str] = None
    """Embedding provider identifier, e.g. ``"openai"`` or ``"cohere"``."""
    embedding_model: Optional[str] = None
    """Model name for embedding generation."""
    llm_provider: Optional[str] = None
    """LLM provider identifier for semantic extraction."""
    llm_model: Optional[str] = None
    """Model name used during consolidation extraction."""

    # -------------------------------------------------------------------
    # Retrieval
    # -------------------------------------------------------------------
    layer_priorities: dict[str, float] = field(
        default_factory=lambda: {"L0": 1.0, "L1": 0.9, "L2": 0.7, "L3": 0.8}
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
                # Faster short-term decay (code context is session-scoped),
                # slightly stronger long-term component for patterns.
                l2_fast_tau=1.5,
                l2_slow_tau=21.0,
                l2_fast_weight=0.35,
                l3_tau=14.0,
                l3_beta=0.25,
                initial_ef=2.5,
                min_ef=1.3,
                review_trigger_retention=0.65,
                archive_threshold=0.25,
                delete_threshold=0.08,
                redundancy_threshold=0.90,
                auto_consolidate=True,
                consolidate_interval_hours=0.5,
                replay_sample_ratio=0.30,
                max_memories_l2=1000,
                max_memories_l3=3000,
                max_skills_l5=500,
                layer_priorities={"L0": 1.0, "L1": 0.95, "L2": 0.75, "L3": 0.85},
            )

        if name == "chat_agent":
            return cls(
                # Fast decay aligned with conversational context windows.
                l2_fast_tau=1.0,
                l2_slow_tau=14.0,
                l2_fast_weight=0.50,
                l3_tau=7.0,
                l3_beta=0.35,
                initial_ef=2.5,
                min_ef=1.3,
                review_trigger_retention=0.75,
                archive_threshold=0.35,
                delete_threshold=0.12,
                redundancy_threshold=0.88,
                auto_consolidate=True,
                consolidate_interval_hours=2.0,
                replay_sample_ratio=0.15,
                max_memories_l2=300,
                max_memories_l3=1000,
                max_skills_l5=100,
                layer_priorities={"L0": 1.0, "L1": 1.0, "L2": 0.65, "L3": 0.75},
            )

        # research_agent — long retention, large capacity, infrequent gc
        return cls(
            l2_fast_tau=3.0,
            l2_slow_tau=60.0,
            l2_fast_weight=0.30,
            l3_tau=20.0,
            l3_beta=0.20,
            initial_ef=2.8,
            min_ef=1.3,
            review_trigger_retention=0.60,
            archive_threshold=0.20,
            delete_threshold=0.06,
            redundancy_threshold=0.95,
            auto_consolidate=True,
            consolidate_interval_hours=4.0,
            replay_sample_ratio=0.10,
            max_memories_l2=2000,
            max_memories_l3=10000,
            max_skills_l5=1000,
            layer_priorities={"L0": 1.0, "L1": 0.85, "L2": 0.80, "L3": 0.95},
        )
