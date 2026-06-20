"""Deterministic tau2 user simulator for offline harness runs."""

from __future__ import annotations

from tau2.data_model.message import AssistantMessage, UserMessage
from tau2.user.user_simulator_base import (
    HalfDuplexUser,
    UserState,
    ValidUserInputMessage,
)

from .loader import _task_reason_for_call


class ScriptedTaskUser(HalfDuplexUser):
    """Replay task scenario text instead of calling an LLM user simulator."""

    def __init__(self, task) -> None:
        super().__init__(instructions=None, tools=None)
        self._task = task
        self._sent_scenario = False

    def set_seed(self, seed: int) -> None:
        return None

    def get_init_state(
        self,
        message_history: list | None = None,
    ) -> UserState:
        messages = list(message_history or [])
        return UserState(messages=messages, system_messages=[])

    def generate_next_message(
        self,
        message: ValidUserInputMessage,
        state: UserState,
    ) -> tuple[UserMessage, UserState]:
        if isinstance(message, AssistantMessage) and message.has_text_content():
            if not self._sent_scenario:
                content = _task_reason_for_call(self._task)
                self._sent_scenario = True
            else:
                content = "Yes, please continue with that."
            user_msg = UserMessage(role="user", content=content)
            state.messages.append(user_msg)
            return user_msg, state
        user_msg = UserMessage(role="user", content="Thanks, that works for me.")
        state.messages.append(user_msg)
        return user_msg, state
