"""In-memory layer sub-package for HM-Arch.

Exposes the shared data type (:class:`LayerItem`), the abstract base class
(:class:`BaseLayer`), and the two concrete in-memory layers:

* :class:`L0SensoryRegister` — tiny bounded window of the most recent events.
* :class:`L1WorkingMemory` — larger bounded store for the current session.

Neither layer has persistence; they exist only for the lifetime of the running
process (or until their :meth:`~BaseLayer.clear` method is called).
"""

from .base import BaseLayer, LayerItem
from .l0_sensory import L0SensoryRegister
from .l1_working import L1WorkingMemory

__all__ = [
    "BaseLayer",
    "LayerItem",
    "L0SensoryRegister",
    "L1WorkingMemory",
]
