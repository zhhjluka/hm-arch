"""Agent integration package for HM-Arch.

Defines the stable adapter protocol, shared offline runtime, and host-specific
adapters for Codex, Claude Code, and Hermes Agent memory provider integrations.
"""

from .config import IntegrationConfig, StorageScope
from .storage_router import MemoryStoreRouter
from .protocol import (
    AdapterOperation,
    ConsolidateRequest,
    ConsolidateResponse,
    ProtocolValidationError,
    RecallRequest,
    RecallResponse,
    RecordRequest,
    RecordResponse,
    fail_open_consolidate,
    fail_open_recall,
    fail_open_record,
    parse_adapter_request,
    validate_operation,
)

__all__ = [
    "AdapterOperation",
    "ConsolidateRequest",
    "ConsolidateResponse",
    "IntegrationConfig",
    "MemoryStoreRouter",
    "ProtocolValidationError",
    "RecallRequest",
    "RecallResponse",
    "RecordRequest",
    "RecordResponse",
    "StorageScope",
    "fail_open_consolidate",
    "fail_open_recall",
    "fail_open_record",
    "parse_adapter_request",
    "validate_operation",
]
