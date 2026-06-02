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
* :class:`SemanticItem` — return type produced by
  :meth:`L3SemanticMemory.search`.

L0 and L1 have no persistence; they exist only for the lifetime of the
running process (or until their :meth:`~BaseLayer.clear` method is called).
L2 and L3 persist to SQLite and survive process restarts.
"""

from .base import BaseLayer, LayerItem
from .l0_sensory import L0SensoryRegister
from .l1_working import L1WorkingMemory
from .l2_episodic import EpisodicItem, L2EpisodicBuffer
from .l3_semantic import SemanticItem, L3SemanticMemory

__all__ = [
    "BaseLayer",
    "LayerItem",
    "L0SensoryRegister",
    "L1WorkingMemory",
    "EpisodicItem",
    "L2EpisodicBuffer",
    "SemanticItem",
    "L3SemanticMemory",
]
