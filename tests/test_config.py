"""Tests for MemoryConfig and its presets."""

from __future__ import annotations

import pytest

from hm_arch import MemoryConfig


# ---------------------------------------------------------------------------
# Default construction
# ---------------------------------------------------------------------------


def test_default_construction() -> None:
    cfg = MemoryConfig()
    assert cfg.db_path == "./.agent_memory.db"
    assert isinstance(cfg.l0_capacity, int)
    assert isinstance(cfg.l1_capacity, int)
    assert isinstance(cfg.l2_capacity, int)
    assert 0.0 < cfg.min_importance < 1.0
    assert 0.0 < cfg.default_importance < 1.0
    assert cfg.consolidation_interval_s > 0


# ---------------------------------------------------------------------------
# Presets return MemoryConfig instances
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["code_agent", "chat_agent", "research_agent"])
def test_preset_returns_memory_config(name: str) -> None:
    cfg = MemoryConfig.preset(name)
    assert isinstance(cfg, MemoryConfig)


# ---------------------------------------------------------------------------
# Presets return distinct configurations
# ---------------------------------------------------------------------------


def test_presets_are_distinct() -> None:
    code = MemoryConfig.preset("code_agent")
    chat = MemoryConfig.preset("chat_agent")
    research = MemoryConfig.preset("research_agent")

    # At least one attribute must differ between every pair
    def differs(a: MemoryConfig, b: MemoryConfig) -> bool:
        return (
            a.l0_capacity != b.l0_capacity
            or a.l1_capacity != b.l1_capacity
            or a.l2_capacity != b.l2_capacity
            or a.min_importance != b.min_importance
            or a.consolidation_interval_s != b.consolidation_interval_s
        )

    assert differs(code, chat), "code_agent and chat_agent must differ"
    assert differs(code, research), "code_agent and research_agent must differ"
    assert differs(chat, research), "chat_agent and research_agent must differ"


# ---------------------------------------------------------------------------
# Each preset has well-formed layer_priorities
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["code_agent", "chat_agent", "research_agent"])
def test_preset_layer_priorities_valid(name: str) -> None:
    cfg = MemoryConfig.preset(name)
    assert set(cfg.layer_priorities.keys()) >= {"L0", "L1", "L2", "L3"}
    for layer, priority in cfg.layer_priorities.items():
        assert 0.0 < priority <= 1.0, f"{name}: {layer} priority {priority} out of range"


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
# Presets can be customised after construction
# ---------------------------------------------------------------------------


def test_preset_is_mutable() -> None:
    cfg = MemoryConfig.preset("code_agent")
    cfg.db_path = "/tmp/custom.db"
    assert cfg.db_path == "/tmp/custom.db"


# ---------------------------------------------------------------------------
# Importability from top-level package
# ---------------------------------------------------------------------------


def test_memory_config_importable_from_hm_arch() -> None:
    import hm_arch

    assert hasattr(hm_arch, "MemoryConfig")
    assert "MemoryConfig" in hm_arch.__all__
