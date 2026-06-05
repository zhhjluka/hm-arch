"""Tests for sensitive-data filtering before memory storage (MEM-58).

Coverage
--------
Detection
* OpenAI, AWS, GitHub, JWT, private key, bearer, and generic secret patterns.
* Environment variable assignments with secret-looking values.
* User-defined custom regex patterns.
* Large tool output truncation.

False positives
* Benign prose mentioning secrets without actual values.
* Boolean/numeric env-style assignments.
* Normal conversation content passes through unchanged.

Integration
* HMArch.add() stores redacted content, not raw secrets.
* Diagnostics on MemoryReceipt and get_stats() omit secret values.
* Filtering can be disabled via MemoryConfig.
"""

from __future__ import annotations

import json

import pytest

from hm_arch import EventType, HMArch, MemoryConfig
from hm_arch.safety.sensitive_data import filter_sensitive_content


_OPENAI_KEY = "sk-" + "A" * 48
_OPENAI_PROJECT_KEY = "sk-proj-" + "B" * 48
_OPENAI_SVCACCT_KEY = "sk-svcacct-" + "C" * 48
_AWS_KEY = "AKIA" + "B" * 16
_GITHUB_TOKEN = "ghp_" + "c" * 36
_JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
    "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
)
_PRIVATE_KEY = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIEpAIBAAKCAQEA1234567890abcdef\n"
    "-----END RSA PRIVATE KEY-----"
)


@pytest.fixture()
def filter_config() -> MemoryConfig:
    return MemoryConfig(
        db_path=":memory:",
        enable_sensitive_data_filter=True,
        max_stored_content_chars=500,
    )


@pytest.fixture()
def memory(filter_config: MemoryConfig) -> HMArch:
    mem = HMArch(config=filter_config)
    yield mem
    mem.close()


def _stored_content(memory: HMArch, memory_id: str) -> str:
    rows = memory._db.query(
        "SELECT content FROM episodes WHERE memory_id = ?",
        (memory_id,),
    )
    assert rows
    return rows[0]["content"]


@pytest.mark.parametrize(
    ("label", "secret_fragment", "category"),
    [
        ("openai", _OPENAI_KEY, "openai_api_key"),
        ("openai_project", _OPENAI_PROJECT_KEY, "openai_api_key"),
        ("openai_svcacct", _OPENAI_SVCACCT_KEY, "openai_api_key"),
        ("aws", _AWS_KEY, "aws_access_key"),
        ("github", _GITHUB_TOKEN, "github_token"),
        ("jwt", _JWT, "jwt"),
        ("private_key", _PRIVATE_KEY, "private_key"),
        ("bearer", "Bearer abcdefghijklmnop", "bearer_token"),
        (
            "generic_secret",
            "api_key=supersecretvalue123456",
            "generic_secret_assignment",
        ),
        (
            "env_var",
            "export DATABASE_PASSWORD=verysecretpass123",
            "env_var_assignment",
        ),
    ],
)
def test_builtin_patterns_detect_secrets(
    filter_config: MemoryConfig,
    label: str,
    secret_fragment: str,
    category: str,
) -> None:
    result = filter_sensitive_content(
        f"Captured during turn: {secret_fragment}",
        filter_config,
    )
    assert secret_fragment not in result.content
    assert result.diagnostics.redactions_by_category.get(category, 0) >= 1


def test_add_stores_redacted_content_not_secrets(memory: HMArch) -> None:
    receipt = memory.add(
        f"Deploy with OPENAI_API_KEY={_OPENAI_KEY} and AWS {_AWS_KEY} "
        f"plus github {_GITHUB_TOKEN}"
    )
    stored = _stored_content(memory, receipt.memory_id)
    assert _OPENAI_KEY not in stored
    assert _AWS_KEY not in stored
    assert _GITHUB_TOKEN not in stored
    assert "[REDACTED]" in stored


def test_diagnostics_on_receipt_do_not_contain_secrets(memory: HMArch) -> None:
    receipt = memory.add(f"Token: {_GITHUB_TOKEN}")
    assert receipt.sensitive_filter is not None
    serialized = json.dumps(receipt.sensitive_filter)
    assert _GITHUB_TOKEN not in serialized
    assert receipt.sensitive_filter["redactions_by_category"]["github_token"] >= 1


def test_get_stats_tracks_safe_diagnostics(memory: HMArch) -> None:
    memory.add(f"Key: {_OPENAI_KEY}")
    memory.add(f"Key: {_AWS_KEY}")
    stats = memory.get_stats()
    diag = stats.sensitive_data_diagnostics
    assert diag["filtered_adds"] == 2
    assert diag.get("redactions.openai_api_key", 0) >= 1
    assert diag.get("redactions.aws_access_key", 0) >= 1
    serialized = json.dumps(diag)
    assert _OPENAI_KEY not in serialized
    assert _AWS_KEY not in serialized


def test_custom_pattern_redacts_user_defined_secret(filter_config: MemoryConfig) -> None:
    filter_config.sensitive_data_patterns = [r"ACME-[0-9]{6}"]
    result = filter_sensitive_content("License ACME-123456 is active", filter_config)
    assert "ACME-123456" not in result.content
    assert result.diagnostics.redactions_by_category["custom_0"] == 1


def test_invalid_custom_pattern_raises(filter_config: MemoryConfig) -> None:
    filter_config.sensitive_data_patterns = ["(?P<bad"]
    with pytest.raises(ValueError, match="Invalid sensitive_data_patterns"):
        filter_sensitive_content("anything", filter_config)


def test_filter_disabled_stores_raw_content() -> None:
    config = MemoryConfig(
        db_path=":memory:",
        enable_sensitive_data_filter=False,
    )
    with HMArch(config=config) as memory:
        receipt = memory.add(f"Keep {_OPENAI_KEY}")
        stored = _stored_content(memory, receipt.memory_id)
        assert _OPENAI_KEY in stored
        assert receipt.sensitive_filter is None


def test_false_positive_benign_secret_mention(filter_config: MemoryConfig) -> None:
    text = "The user asked about API keys in general, not a specific value."
    result = filter_sensitive_content(text, filter_config)
    assert result.content == text
    assert not result.diagnostics.was_modified


def test_false_positive_boolean_env_assignment(filter_config: MemoryConfig) -> None:
    text = "Set DEBUG=true and PORT=8080 in your shell profile."
    result = filter_sensitive_content(text, filter_config)
    assert result.content == text
    assert not result.diagnostics.was_modified


def test_false_positive_normal_conversation(memory: HMArch) -> None:
    text = "User prefers pytest and uv for offline verification."
    receipt = memory.add(text, event_type=EventType.CONVERSATION)
    stored = _stored_content(memory, receipt.memory_id)
    assert stored == text
    assert receipt.sensitive_filter is None


def test_large_tool_output_truncated(filter_config: MemoryConfig) -> None:
    filter_config.max_stored_content_chars = 200
    huge = "x" * 1000
    result = filter_sensitive_content(huge, filter_config)
    assert len(result.content) <= 200
    assert result.diagnostics.truncated is True
    assert "truncated" in result.content


def test_openai_project_key_redacted_in_content_and_metadata(memory: HMArch) -> None:
    receipt = memory.add(
        f"bare project key {_OPENAI_PROJECT_KEY}",
        metadata={"nested": {"openai": _OPENAI_PROJECT_KEY}},
    )
    stored = _stored_content(memory, receipt.memory_id)
    assert _OPENAI_PROJECT_KEY not in stored
    assert "[REDACTED]" in stored

    rows = memory._db.query(
        "SELECT metadata FROM memory_index WHERE id = ?",
        (receipt.memory_id,),
    )
    meta = json.loads(rows[0]["metadata"])
    assert _OPENAI_PROJECT_KEY not in json.dumps(meta)
    assert "[REDACTED]" in meta["nested"]["openai"]

    assert receipt.sensitive_filter is not None
    assert receipt.sensitive_filter["redactions_by_category"]["openai_api_key"] >= 2
    serialized = json.dumps(receipt.sensitive_filter)
    assert _OPENAI_PROJECT_KEY not in serialized


def test_metadata_string_values_are_filtered(memory: HMArch) -> None:
    receipt = memory.add(
        "Benign summary",
        metadata={"token": _GITHUB_TOKEN, "note": "safe"},
    )
    rows = memory._db.query(
        "SELECT metadata FROM memory_index WHERE id = ?",
        (receipt.memory_id,),
    )
    meta = json.loads(rows[0]["metadata"])
    assert _GITHUB_TOKEN not in meta["token"]
    assert "[REDACTED]" in meta["token"]


def test_search_returns_redacted_content(memory: HMArch) -> None:
    memory.add(f"Credential {_OPENAI_KEY} for deployment")
    hits = memory.search("deployment credential", top_k=1)
    assert hits.results
    assert _OPENAI_KEY not in hits.results[0].content
    assert "[REDACTED]" in hits.results[0].content
