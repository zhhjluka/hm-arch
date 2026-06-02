import pytest

from hm_arch import MemoryConfig


def test_default_memory_config_uses_local_offline_settings() -> None:
    config = MemoryConfig()

    assert config.vector_backend == "local"
    assert config.llm_provider is None
    assert config.default_top_k > 0


def test_presets_return_distinct_values() -> None:
    code_agent = MemoryConfig.preset("code_agent")
    chat_agent = MemoryConfig.preset("chat_agent")
    research_agent = MemoryConfig.preset("research_agent")

    assert code_agent != chat_agent
    assert chat_agent != research_agent
    assert research_agent != code_agent
    assert code_agent.metadata["preset"] == "code_agent"
    assert chat_agent.metadata["preset"] == "chat_agent"
    assert research_agent.metadata["preset"] == "research_agent"


def test_preset_name_is_case_and_space_tolerant() -> None:
    assert MemoryConfig.preset(" Code_Agent ").metadata["preset"] == "code_agent"


def test_unknown_preset_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown memory config preset"):
        MemoryConfig.preset("unknown")


def test_config_metadata_defaults_are_isolated() -> None:
    first = MemoryConfig()
    second = MemoryConfig()

    first.metadata["key"] = "value"

    assert second.metadata == {}
