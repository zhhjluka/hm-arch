"""Configuration object and built-in presets for HM-Arch."""

from __future__ import annotations

from dataclasses import dataclass, field

_VALID_PRESETS = {"code_agent", "chat_agent", "research_agent"}


@dataclass
class MemoryConfig:
    """Runtime configuration for an :py:class:`HMArch` instance.

    All capacity values represent maximum item counts for the respective
    memory layers.  Decay and scoring parameters follow the PRD formulas.
    """

    db_path: str = "./.agent_memory.db"

    # Layer capacities
    l0_capacity: int = 5
    l1_capacity: int = 20
    l2_capacity: int = 500

    # Importance / filtering
    min_importance: float = 0.3
    default_importance: float = 0.5

    # Consolidation
    consolidation_interval_s: int = 3600

    # Decay parameters (L2 bi-exponential, L3 power-law)
    l2_decay_fast_rate: float = 0.7
    l2_decay_slow_rate: float = 0.1
    l2_decay_fast_weight: float = 0.4
    l3_decay_rate: float = 0.25

    # Retrieval scoring
    layer_priorities: dict[str, float] = field(
        default_factory=lambda: {"L0": 1.0, "L1": 0.9, "L2": 0.7, "L3": 0.8}
    )

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
                l0_capacity=8,
                l1_capacity=30,
                l2_capacity=1000,
                min_importance=0.4,
                default_importance=0.6,
                consolidation_interval_s=1800,
                l2_decay_fast_rate=0.6,
                l2_decay_slow_rate=0.08,
                l2_decay_fast_weight=0.35,
                l3_decay_rate=0.20,
                layer_priorities={"L0": 1.0, "L1": 0.95, "L2": 0.75, "L3": 0.85},
            )

        if name == "chat_agent":
            return cls(
                l0_capacity=10,
                l1_capacity=50,
                l2_capacity=300,
                min_importance=0.2,
                default_importance=0.4,
                consolidation_interval_s=7200,
                l2_decay_fast_rate=0.8,
                l2_decay_slow_rate=0.12,
                l2_decay_fast_weight=0.45,
                l3_decay_rate=0.30,
                layer_priorities={"L0": 1.0, "L1": 1.0, "L2": 0.65, "L3": 0.75},
            )

        # research_agent
        return cls(
            l0_capacity=5,
            l1_capacity=20,
            l2_capacity=2000,
            min_importance=0.15,
            default_importance=0.5,
            consolidation_interval_s=14400,
            l2_decay_fast_rate=0.5,
            l2_decay_slow_rate=0.06,
            l2_decay_fast_weight=0.30,
            l3_decay_rate=0.15,
            layer_priorities={"L0": 1.0, "L1": 0.85, "L2": 0.80, "L3": 0.95},
        )
