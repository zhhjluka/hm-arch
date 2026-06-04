"""Turn recording for agent turn-end hooks."""

from __future__ import annotations

from hm_arch import EventType, HMArch


def record_turn_end(
    memory: HMArch,
    user_message: str,
    agent_message: str,
) -> list[str]:
    """Persist user and assistant messages from a completed turn."""
    recorded: list[str] = []
    user_message = user_message.strip()
    agent_message = agent_message.strip()

    if user_message:
        receipt = memory.add(
            f"User: {user_message}",
            event_type=EventType.CONVERSATION,
            importance=0.7,
        )
        recorded.append(receipt.memory_id)

    if agent_message:
        receipt = memory.add(
            f"Assistant: {agent_message}",
            event_type=EventType.CONVERSATION,
            importance=0.6,
        )
        recorded.append(receipt.memory_id)

    return recorded
