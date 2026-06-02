"""Layer sub-package for HM-Arch.

Exposes the shared data type (:class:`LayerItem`), the abstract base class
(:class:`BaseLayer`), and the concrete layer implementations:

* :class:`L0SensoryRegister` — tiny bounded in-memory window of recent events.
* :class:`L1WorkingMemory` — larger bounded in-memory store for the session.
* :class:`L2EpisodicBuffer` — durable episodic buffer backed by SQLite and a
  vector store; persists across process restarts.

L0 and L1 are purely in-memory and exist only for the lifetime of the running
process.  L2 writes to SQLite on every :meth:`~L2EpisodicBuffer.encode` call
so that content survives restarts.
"""

from .base import BaseLayer, LayerItem
from .l0_sensory import L0SensoryRegister
from .l1_working import L1WorkingMemory
from .l2_episodic import L2EpisodicBuffer

__all__ = [
    "BaseLayer",
    "LayerItem",
    "L0SensoryRegister",
    "L1WorkingMemory",
    "L2EpisodicBuffer",
]
