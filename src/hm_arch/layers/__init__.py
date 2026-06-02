"""Memory layer sub-package for HM-Arch.

Exposes the shared data type (:class:`LayerItem`), the abstract base class
(:class:`BaseLayer`), the two concrete in-memory layers, and the durable
episodic buffer:

* :class:`L0SensoryRegister` — tiny bounded window of the most recent events.
* :class:`L1WorkingMemory` — larger bounded store for the current session.
* :class:`L2EpisodicBuffer` — durable SQLite + vector-store episodic layer.
* :class:`EpisodicItem` — return type produced by
  :meth:`L2EpisodicBuffer.retrieve`.

L0 and L1 have no persistence; they exist only for the lifetime of the
running process (or until their :meth:`~BaseLayer.clear` method is called).
L2 persists to SQLite and survives process restarts.
"""

from .base import BaseLayer, LayerItem
from .l0_sensory import L0SensoryRegister
from .l1_working import L1WorkingMemory
from .l2_episodic import EpisodicItem, L2EpisodicBuffer

__all__ = [
    "BaseLayer",
    "LayerItem",
    "L0SensoryRegister",
    "L1WorkingMemory",
    "EpisodicItem",
    "L2EpisodicBuffer",
]
