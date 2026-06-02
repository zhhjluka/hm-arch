"""Tests for MemoryConfig and its presets.

All assertions use the canonical PRD field names so that later modules can
rely on these names without guessing.
"""

from __future__ import annotations

import dataclasses

import pytest

from hm_arch import MemoryConfig


def _field_names(cls: type) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


# ---------------------------------------------------------------------------
# Required PRD fields are present
# ---------------------------------------------------------------------------


REQUIRED_FIELDS = {
    # Decay — L2
    "l2_fast_tau",
    "l2_slow_tau",
    "l2_fast_weight",
    # Decay — L3
    "l3_tau",
    "l3_beta",
    # ASM-2
    "initial_ef",
    "min_ef",
    "review_trigger_retention",
    # Thresholds
    "l2_archive_threshold",
    "l2_delete_threshold",
    "l3_archive_threshold",
    "l3_delete_threshold",
    "redundancy_threshold",
    # Consolidation
    "auto_consolidate",
    "consolidate_interval_hours",
    "replay_sample_ratio",
    # Storage caps
    "max_memories_l2",
    "max_memories_l3",
    "max_skills_l5",
    # Providers
    "llm_provider",
    "llm_model",
    "llm_api_key",
    "llm_base_url",
    "embedding_provider",
    "embedding_model",
    "embedding_dim",
    # Database
    "db_path",
    "archive_root",
    # Retrieval
    "layer_priorities",
}


def test_required_fields_present() -> None:
    missing = REQUIRED_FIELDS - _field_names(MemoryConfig)
    assert not missing, f"MemoryConfig is missing PRD fields: {sorted(missing)}"


# ---------------------------------------------------------------------------
# Default values are sane
# ---------------------------------------------------------------------------


def test_default_db_path() -> None:
    assert MemoryConfig().db_path == "./.agent_memory.db"


def test_default_decay_l2() -> None:
    cfg = MemoryConfig()
    assert cfg.l2_fast_tau == pytest.approx(24.0)
    assert cfg.l2_slow_tau == pytest.approx(720.0)
    assert cfg.l2_fast_weight == pytest.approx(0.30)


def test_default_decay_l3() -> None:
    cfg = MemoryConfig()
    assert cfg.l3_tau == pytest.approx(168.0)
    assert cfg.l3_beta == pytest.approx(0.30)


def test_default_asm2() -> None:
    cfg = MemoryConfig()
    assert cfg.initial_ef == pytest.approx(2.5)
    assert cfg.min_ef == pytest.approx(1.3)
    assert cfg.review_trigger_retention == pytest.approx(0.50)


def test_default_thresholds_ordered() -> None:
    cfg = MemoryConfig()
    assert cfg.l2_delete_threshold == pytest.approx(0.05)
    assert cfg.l2_archive_threshold == pytest.approx(0.15)
    assert cfg.l3_delete_threshold == pytest.approx(0.10)
    assert cfg.l3_archive_threshold == pytest.approx(0.30)
    assert cfg.redundancy_threshold == pytest.approx(0.85)
    assert cfg.l2_delete_threshold < cfg.l2_archive_threshold < cfg.review_trigger_retention
    assert cfg.l3_delete_threshold < cfg.l3_archive_threshold < cfg.review_trigger_retention


def test_default_consolidation_settings() -> None:
    cfg = MemoryConfig()
    assert cfg.auto_consolidate is True
    assert cfg.consolidate_interval_hours == 24
    assert cfg.replay_sample_ratio == pytest.approx(0.20)


def test_default_storage_caps() -> None:
    cfg = MemoryConfig()
    assert cfg.max_memories_l2 == 100000
    assert cfg.max_memories_l3 == 50000
    assert cfg.max_skills_l5 == 10000


def test_default_providers_match_prd() -> None:
    cfg = MemoryConfig()
    assert cfg.llm_provider == "deepseek"
    assert cfg.llm_model == "deepseek-v4-flash"
    assert cfg.llm_api_key is None
    assert cfg.llm_base_url is None
    assert cfg.embedding_provider == "deepseek"
    assert cfg.embedding_model == "deepseek-v4-flash"
    assert cfg.embedding_dim == 1536


def test_default_layer_priorities_cover_all_layers() -> None:
    cfg = MemoryConfig()
    assert set(cfg.layer_priorities.keys()) >= {"L0", "L1", "L2", "L3", "L4"}
    for layer, priority in cfg.layer_priorities.items():
        assert 0.0 < priority <= 1.0, f"{layer} priority {priority} out of (0, 1]"
    assert cfg.layer_priorities["L4"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Presets return MemoryConfig instances
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["code_agent", "chat_agent", "research_agent"])
def test_preset_returns_memory_config(name: str) -> None:
    cfg = MemoryConfig.preset(name)
    assert isinstance(cfg, MemoryConfig)


# ---------------------------------------------------------------------------
# Presets carry all required fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["code_agent", "chat_agent", "research_agent"])
def test_preset_has_all_required_fields(name: str) -> None:
    cfg = MemoryConfig.preset(name)
    missing = REQUIRED_FIELDS - _field_names(type(cfg))
    assert not missing, f"{name} preset missing fields: {sorted(missing)}"


# ---------------------------------------------------------------------------
# Presets return distinct configurations
# ---------------------------------------------------------------------------


def test_presets_are_mutually_distinct() -> None:
    code = MemoryConfig.preset("code_agent")
    chat = MemoryConfig.preset("chat_agent")
    research = MemoryConfig.preset("research_agent")

    def has_unique_value(a: MemoryConfig, b: MemoryConfig) -> bool:
        for f in dataclasses.fields(a):
            if f.name in {
                "db_path",
                "layer_priorities",
                "initial_ef",
                "min_ef",
                "embedding_provider",
                "embedding_model",
                "embedding_dim",
                "llm_provider",
                "llm_model",
                "llm_api_key",
                "llm_base_url",
                "auto_consolidate",
            }:
                continue
            if getattr(a, f.name) != getattr(b, f.name):
                return True
        return False

    assert has_unique_value(code, chat), "code_agent and chat_agent must differ"
    assert has_unique_value(code, research), "code_agent and research_agent must differ"
    assert has_unique_value(chat, research), "chat_agent and research_agent must differ"


# ---------------------------------------------------------------------------
# Preset invariants: decay ordering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["code_agent", "chat_agent", "research_agent"])
def test_preset_slow_tau_exceeds_fast_tau(name: str) -> None:
    cfg = MemoryConfig.preset(name)
    assert cfg.l2_slow_tau > cfg.l2_fast_tau, (
        f"{name}: l2_slow_tau ({cfg.l2_slow_tau}) must be > l2_fast_tau ({cfg.l2_fast_tau})"
    )


@pytest.mark.parametrize("name", ["code_agent", "chat_agent", "research_agent"])
def test_preset_threshold_ordering(name: str) -> None:
    cfg = MemoryConfig.preset(name)
    assert cfg.l2_delete_threshold < cfg.l2_archive_threshold < cfg.review_trigger_retention, (
        f"{name}: L2 thresholds must satisfy delete < archive < review_trigger"
    )
    assert cfg.l3_delete_threshold < cfg.l3_archive_threshold < cfg.review_trigger_retention, (
        f"{name}: L3 thresholds must satisfy delete < archive < review_trigger"
    )


@pytest.mark.parametrize("name", ["code_agent", "chat_agent", "research_agent"])
def test_preset_layer_priorities_valid(name: str) -> None:
    cfg = MemoryConfig.preset(name)
    assert set(cfg.layer_priorities.keys()) >= {"L0", "L1", "L2", "L3", "L4"}
    for layer, priority in cfg.layer_priorities.items():
        assert 0.0 < priority <= 1.0, f"{name}: {layer} priority {priority} out of (0,1]"
    assert cfg.layer_priorities["L4"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Unknown preset raises ValueError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_name",
    ["unknown", "CODE_AGENT", "chat agent", "", "default", "GPT"],
)
def test_unknown_preset_raises_value_error(bad_name: str) -> None:
    with pytest.raises(ValueError, match="Unknown preset"):
        MemoryConfig.preset(bad_name)


# ---------------------------------------------------------------------------
# Preset is mutable after construction
# ---------------------------------------------------------------------------


def test_preset_is_mutable() -> None:
    cfg = MemoryConfig.preset("code_agent")
    cfg.db_path = "/tmp/test.db"
    cfg.llm_provider = "openai"
    assert cfg.db_path == "/tmp/test.db"
    assert cfg.llm_provider == "openai"


# ---------------------------------------------------------------------------
# Top-level importability
# ---------------------------------------------------------------------------


def test_memory_config_exported_from_hm_arch() -> None:
    import hm_arch

    assert hasattr(hm_arch, "MemoryConfig")
    assert "MemoryConfig" in hm_arch.__all__
