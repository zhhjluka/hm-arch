from dataclasses import is_dataclass

from hm_arch import (
    ConsolidationReport,
    EventType,
    MemoryItem,
    MemoryReceipt,
    MemoryStats,
    RetentionCurve,
    SearchResult,
)


def test_public_type_objects_are_dataclasses() -> None:
    assert is_dataclass(MemoryReceipt)
    assert is_dataclass(MemoryItem)
    assert is_dataclass(SearchResult)
    assert is_dataclass(ConsolidationReport)
    assert is_dataclass(RetentionCurve)
    assert is_dataclass(MemoryStats)


def test_event_type_is_string_enum() -> None:
    assert EventType.CONVERSATION.value == "conversation"
    assert EventType("conversation") is EventType.CONVERSATION
    assert isinstance(EventType.CONVERSATION.value, str)


def test_public_dataclasses_construct_with_expected_defaults() -> None:
    receipt = MemoryReceipt(memory_id="mem-1", layer="L2")
    item = MemoryItem(memory_id="mem-1", content="User prefers Python", layer="L2")
    result = SearchResult(item=item, relevance=0.7, retention=0.8)
    report = ConsolidationReport(episodes_processed=2, semantic_memories_created=1)
    curve = RetentionCurve(memory_id="mem-1", layer="L2", current_retention=0.8)
    stats = MemoryStats(total_memories=1, by_layer={"L2": 1})

    assert receipt.event_type is EventType.OTHER
    assert item.event_type is EventType.OTHER
    assert result.score == 0.56
    assert report.semantic_memories_created == 1
    assert curve.points == ()
    assert stats.by_layer == {"L2": 1}


def test_dataclass_mutable_defaults_are_isolated() -> None:
    first = MemoryItem(memory_id="first", content="one", layer="L2")
    second = MemoryItem(memory_id="second", content="two", layer="L2")

    first.metadata["source"] = "test"

    assert second.metadata == {}
