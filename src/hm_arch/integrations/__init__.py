"""Agent integration foundations for HM-Arch.

This package defines the stable JSON protocol, integration configuration, and
shared execution helpers used by future Codex, Claude Code, and Hermes adapters.
Host-specific installers and CLI entry points live in later releases.
"""

from .config import IntegrationConfig, IntegrationScope
from .errors import (
    FAIL_OPEN_ERROR_CODES,
    AdapterFailOpenResponse,
    fail_open_response,
)
from .executor import execute_adapter_request
from .protocol import (
    AgentOperation,
    ConsolidateRequest,
    ConsolidateResponse,
    ProtocolValidationError,
    RecallRequest,
    RecallResponse,
    RecordRequest,
    RecordResponse,
    parse_adapter_request,
)

__all__ = [
    "AgentOperation",
    "AdapterFailOpenResponse",
    "ConsolidateRequest",
    "ConsolidateResponse",
    "FAIL_OPEN_ERROR_CODES",
    "IntegrationConfig",
    "IntegrationScope",
    "ProtocolValidationError",
    "RecallRequest",
    "RecallResponse",
    "RecordRequest",
    "RecordResponse",
    "execute_adapter_request",
    "fail_open_response",
    "parse_adapter_request",
]
