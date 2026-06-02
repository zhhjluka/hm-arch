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
    "archive_threshold",
    "delete_threshold",
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
    "embedding_provider",
    "embedding_model",
    "llm_provider",
    "llm_model",
    # Database
    "db_path",
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
    assert cfg.l2_fast_tau > 0
    assert cfg.l2_slow_tau > cfg.l2_fast_tau, "slow tau must be larger than fast tau"
    assert 0.0 < cfg.l2_fast_weight < 1.0


def test_default_decay_l3() -> None:
    cfg = MemoryConfig()
    assert cfg.l3_tau > 0
    assert cfg.l3_beta > 0


def test_default_asm2() -> None:
    cfg = MemoryConfig()
    assert cfg.initial_ef > cfg.min_ef
    assert 0.0 < cfg.review_trigger_retention < 1.0


def test_default_thresholds_ordered() -> None:
    cfg = MemoryConfig()
    assert cfg.delete_threshold < cfg.archive_threshold < cfg.review_trigger_retention


def test_default_consolidation_settings() -> None:
    cfg = MemoryConfig()
    assert isinstance(cfg.auto_consolidate, bool)
    assert cfg.consolidate_interval_hours > 0
    assert 0.0 < cfg.replay_sample_ratio <= 1.0


def test_default_storage_caps() -> None:
    cfg = MemoryConfig()
    assert cfg.max_memories_l2 > 0
    assert cfg.max_memories_l3 > 0
    assert cfg.max_skills_l5 > 0


def test_default_providers_are_none() -> None:
    cfg = MemoryConfig()
    assert cfg.embedding_provider is None
    assert cfg.embedding_model is None
    assert cfg.llm_provider is None
    assert cfg.llm_model is None


def test_default_layer_priorities_cover_all_layers() -> None:
    cfg = MemoryConfig()
    assert set(cfg.layer_priorities.keys()) >= {"L0", "L1", "L2", "L3"}
    for layer, priority in cfg.layer_priorities.items():
        assert 0.0 < priority <= 1.0, f"{layer} priority {priority} out of (0, 1]"


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
            if f.name in {"db_path", "layer_priorities", "initial_ef", "min_ef",
                          "embedding_provider", "embedding_model", "llm_provider",
                          "llm_model", "auto_consolidate"}:
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
    assert cfg.delete_threshold < cfg.archive_threshold < cfg.review_trigger_retention, (
        f"{name}: thresholds must satisfy delete < archive < review_trigger"
    )


@pytest.mark.parametrize("name", ["code_agent", "chat_agent", "research_agent"])
def test_preset_layer_priorities_valid(name: str) -> None:
    cfg = MemoryConfig.preset(name)
    assert set(cfg.layer_priorities.keys()) >= {"L0", "L1", "L2", "L3"}
    for layer, priority in cfg.layer_priorities.items():
        assert 0.0 < priority <= 1.0, f"{name}: {layer} priority {priority} out of (0,1]"


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
