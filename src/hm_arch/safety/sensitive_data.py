"""Sensitive-data filtering before memory storage (MEM-58).

Detects and redacts common secret patterns, truncates oversized tool outputs,
and supports user-defined regex patterns.  Diagnostics record category counts
only — never the matched secret values.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from hm_arch.config import MemoryConfig

_REDACTION_DEFAULT = "[REDACTED]"

# Built-in detectors: (category_name, compiled_pattern).
_BUILTIN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "openai_api_key",
        re.compile(r"sk-[A-Za-z0-9]{20,}(?:T3BlbkFJ[A-Za-z0-9]{20,})?"),
    ),
    (
        "aws_access_key",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    ),
    (
        "github_token",
        re.compile(
            r"\b(?:ghp_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{20,})\b"
        ),
    ),
    (
        "jwt",
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
        ),
    ),
    (
        "private_key",
        re.compile(
            r"-----BEGIN(?:\s+(?:RSA|EC|OPENSSH|ENCRYPTED))?\s+PRIVATE\s+KEY-----"
            r"[\s\S]*?"
            r"-----END(?:\s+(?:RSA|EC|OPENSSH|ENCRYPTED))?\s+PRIVATE\s+KEY-----",
            re.MULTILINE,
        ),
    ),
    (
        "bearer_token",
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/]{8,}={0,2}\b"),
    ),
    (
        "generic_secret_assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|apikey|secret[_-]?key|access[_-]?token|"
            r"auth[_-]?token|client[_-]?secret|password|passwd|pwd)\s*"
            r"[:=]\s*['\"]?[\w\-./+=@]{8,}['\"]?"
        ),
    ),
    (
        "env_var_assignment",
        re.compile(
            r"(?:(?<=\n)|^|\s)(?:export\s+)?[A-Z][A-Z0-9_]{2,}="
            r"(?!['\"]?(?:true|false|null|none|undefined)['\"]?(?:\s|$))"
            r"(?!['\"]?\d{1,6}['\"]?(?:\s|$))"
            r"[^\s'\"]{8,}"
        ),
    ),
)


@dataclass(frozen=True)
class SensitiveFilterDiagnostics:
    """Safe summary of filtering applied to stored content.

    Counts and category names only — never the redacted secret values.
    """

    redactions_by_category: dict[str, int] = field(default_factory=dict)
    truncated: bool = False
    original_length: int = 0
    filtered_length: int = 0

    @property
    def total_redactions(self) -> int:
        return sum(self.redactions_by_category.values())

    @property
    def was_modified(self) -> bool:
        return self.total_redactions > 0 or self.truncated

    def to_metadata(self) -> dict[str, Any]:
        """Return a JSON-serializable metadata fragment."""
        return {
            "redactions_by_category": dict(self.redactions_by_category),
            "truncated": self.truncated,
            "original_length": self.original_length,
            "filtered_length": self.filtered_length,
        }


@dataclass(frozen=True)
class SensitiveFilterResult:
    """Output of :func:`filter_sensitive_content`."""

    content: str
    diagnostics: SensitiveFilterDiagnostics


def _compile_custom_patterns(patterns: Iterable[str]) -> list[tuple[str, re.Pattern[str]]]:
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for index, raw in enumerate(patterns):
        label = f"custom_{index}"
        try:
            compiled.append((label, re.compile(raw)))
        except re.error as exc:
            raise ValueError(f"Invalid sensitive_data_patterns[{index}]: {exc}") from exc
    return compiled


def _redact_matches(
    text: str,
    patterns: Iterable[tuple[str, re.Pattern[str]]],
    redaction_token: str,
) -> tuple[str, dict[str, int]]:
    redactions: dict[str, int] = {}
    result = text
    for category, pattern in patterns:
        matches = list(pattern.finditer(result))
        if not matches:
            continue
        redactions[category] = redactions.get(category, 0) + len(matches)
        result = pattern.sub(redaction_token, result)
    return result, redactions


def _truncate_large_content(
    content: str,
    max_chars: int,
    redaction_token: str,
) -> tuple[str, bool]:
    if max_chars <= 0 or len(content) <= max_chars:
        return content, False
    suffix = (
        f"\n\n{redaction_token}: content truncated "
        f"({len(content)} chars -> {max_chars} chars)"
    )
    keep = max(0, max_chars - len(suffix))
    return content[:keep] + suffix, True


def filter_sensitive_content(
    content: str,
    config: MemoryConfig,
) -> SensitiveFilterResult:
    """Redact sensitive patterns and truncate oversized content.

    When ``enable_sensitive_data_filter`` is ``False``, returns *content*
    unchanged with empty diagnostics.
    """
    original_length = len(content)
    if not config.enable_sensitive_data_filter:
        return SensitiveFilterResult(
            content=content,
            diagnostics=SensitiveFilterDiagnostics(
                original_length=original_length,
                filtered_length=original_length,
            ),
        )

    redaction_token = config.sensitive_data_redaction_token
    patterns = list(_BUILTIN_PATTERNS)
    patterns.extend(_compile_custom_patterns(config.sensitive_data_patterns))

    filtered, redactions = _redact_matches(content, patterns, redaction_token)
    filtered, truncated = _truncate_large_content(
        filtered,
        config.max_stored_content_chars,
        redaction_token,
    )

    diagnostics = SensitiveFilterDiagnostics(
        redactions_by_category=redactions,
        truncated=truncated,
        original_length=original_length,
        filtered_length=len(filtered),
    )
    return SensitiveFilterResult(content=filtered, diagnostics=diagnostics)


def filter_metadata_values(
    metadata: dict[str, Any] | None,
    config: MemoryConfig,
) -> tuple[dict[str, Any] | None, SensitiveFilterDiagnostics]:
    """Apply sensitive-data filtering to string metadata values."""
    if metadata is None or not config.enable_sensitive_data_filter:
        return metadata, SensitiveFilterDiagnostics()

    merged_redactions: dict[str, int] = {}
    truncated = False
    original_length = 0
    filtered_length = 0
    filtered_meta: dict[str, Any] = {}

    for key, value in metadata.items():
        if isinstance(value, str):
            result = filter_sensitive_content(value, config)
            filtered_meta[key] = result.content
            original_length += result.diagnostics.original_length
            filtered_length += result.diagnostics.filtered_length
            truncated = truncated or result.diagnostics.truncated
            for cat, count in result.diagnostics.redactions_by_category.items():
                merged_redactions[cat] = merged_redactions.get(cat, 0) + count
        elif isinstance(value, dict):
            nested, nested_diag = filter_metadata_values(value, config)
            filtered_meta[key] = nested
            original_length += nested_diag.original_length
            filtered_length += nested_diag.filtered_length
            truncated = truncated or nested_diag.truncated
            for cat, count in nested_diag.redactions_by_category.items():
                merged_redactions[cat] = merged_redactions.get(cat, 0) + count
        else:
            filtered_meta[key] = value

    diagnostics = SensitiveFilterDiagnostics(
        redactions_by_category=merged_redactions,
        truncated=truncated,
        original_length=original_length,
        filtered_length=filtered_length,
    )
    return filtered_meta, diagnostics


def merge_diagnostics(
    *diagnostics: SensitiveFilterDiagnostics,
) -> SensitiveFilterDiagnostics:
    """Combine diagnostics from content and metadata filtering."""
    merged: dict[str, int] = {}
    truncated = False
    original_length = 0
    filtered_length = 0
    for diag in diagnostics:
        truncated = truncated or diag.truncated
        original_length += diag.original_length
        filtered_length += diag.filtered_length
        for cat, count in diag.redactions_by_category.items():
            merged[cat] = merged.get(cat, 0) + count
    return SensitiveFilterDiagnostics(
        redactions_by_category=merged,
        truncated=truncated,
        original_length=original_length,
        filtered_length=filtered_length,
    )
