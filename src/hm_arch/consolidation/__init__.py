"""Consolidation engine for HM-Arch.

Turns episodic memories into semantic facts, updates retention fields,
and schedules reviews for important low-retention memories.
"""

from .replay import ConsolidationEngine, SemanticExtractor

__all__ = [
    "ConsolidationEngine",
    "SemanticExtractor",
]
