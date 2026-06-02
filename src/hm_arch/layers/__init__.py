"""Memory layer sub-package for HM-Arch.

Exposes the shared data type (:class:`LayerItem`), the abstract base class
(:class:`BaseLayer`), the two concrete in-memory layers, the durable episodic
buffer, and the durable semantic triple store:

* :class:`L0SensoryRegister` — tiny bounded window of the most recent events.
* :class:`L1WorkingMemory` — larger bounded store for the current session.
* :class:`L2EpisodicBuffer` — durable SQLite + vector-store episodic layer.
* :class:`EpisodicItem` — return type produced by
  :meth:`L2EpisodicBuffer.retrieve`.
* :class:`L3SemanticMemory` — durable SQLite + vector-store semantic triple
  layer.
* :class:`SemanticFact` — return type produced by
  :meth:`L3SemanticMemory.search` and :meth:`L3SemanticMemory.upsert`.
* :class:`L4EpisodicLTM` — gzip-compressed filesystem archive for low-retention
  episodic memories.
* :class:`ArchivedEpisodic` — return type produced by
  :meth:`L4EpisodicLTM.retrieve`.
* :class:`L5ProceduralMemory` — durable SQLite store for procedural skills.
* :class:`SkillRecord` — return type produced by L5 skill operations.
* :class:`L6MetaMemory` — usage tracking and deterministic meta policies.
* :class:`HotMemoryRecord` — return type from :meth:`L6MetaMemory.get_hot_memories`.
* :class:`StrategyPlan` — return type from :meth:`L6MetaMemory.strategy_plan`.

L0 and L1 have no persistence; they exist only for the lifetime of the
running process (or until their :meth:`~BaseLayer.clear` method is called).
L2, L3, L5, and L6 persist to SQLite and survive process restarts.
L4 persists compressed JSON under ``ltm/YYYY-MM/`` on the filesystem.
"""

from .base import BaseLayer, LayerItem
from .l0_sensory import L0SensoryRegister
from .l1_working import L1WorkingMemory
from .l2_episodic import EpisodicItem, L2EpisodicBuffer
from .l3_semantic import SemanticFact, L3SemanticMemory
from .l4_ltm import ArchivedEpisodic, L4EpisodicLTM
from .l5_procedural import L5ProceduralMemory, SkillRecord
from .l6_meta import HotMemoryRecord, L6MetaMemory, StrategyPlan

__all__ = [
    "BaseLayer",
    "LayerItem",
    "L0SensoryRegister",
    "L1WorkingMemory",
    "EpisodicItem",
    "L2EpisodicBuffer",
    "SemanticFact",
    "L3SemanticMemory",
    "ArchivedEpisodic",
    "L4EpisodicLTM",
    "L5ProceduralMemory",
    "SkillRecord",
    "L6MetaMemory",
    "HotMemoryRecord",
    "StrategyPlan",
]
