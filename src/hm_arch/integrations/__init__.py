"""Agent integration package for HM-Arch.

This package defines the stable adapter protocol and integration configuration
used by host-specific adapters (Codex, Claude Code, Hermes). Host adapters are
implemented in later issues; this module only provides the shared contract.
"""

from .config import IntegrationConfig, StorageScope
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
