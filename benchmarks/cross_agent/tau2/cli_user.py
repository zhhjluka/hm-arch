"""CLI-backed tau2 user simulator for credential-free REAL mode."""

from __future__ import annotations

import json
from pathlib import Path

from ..agents.cli_process import CliInvocationError, resolve_agent_executable, run_cli
from .agent_cli import is_harness_executable
from ..agents.cli_parsers import parse_claude_json_output, parse_codex_exec_jsonl
from .availability import _stub_tau2_optional_deps
from .loader import _task_reason_for_call

_stub_tau2_optional_deps()

from tau2.data_model.message import AssistantMessage, UserMessage
from tau2.user.user_simulator_base import (
    HalfDuplexUser,
    UserState,
    ValidUserInputMessage,
)

CLI_USER_SIMULATOR_LABEL = "cli_user_simulator"
_SUPPORTED_USER_CLIS = ("codex", "claude")


def resolve_user_cli_executable(
    *,
    preference: str = "auto",
    override: str | None = None,
    production_only: bool = False,
) -> tuple[str | None, str | None]:
    """Return (executable, cli_kind) for codex or claude user simulation."""
    if override:
        if production_only and is_harness_executable(override):
            return None, None
        lowered = Path(override).name.lower()
        if "claude" in lowered:
            return override, "claude"
        return override, "codex"
    choices = _SUPPORTED_USER_CLIS if preference == "auto" else (preference,)
    for kind in choices:
        default_names = ("codex",) if kind == "codex" else ("claude",)
        resolved = resolve_agent_executable(
            kind,
            default_names=default_names,
            production_only=production_only,
        )
        if resolved is not None and not is_harness_executable(resolved):
            return resolved, kind
    return None, None


def _parse_user_cli_text(stdout: str, *, cli_kind: str, argv: tuple[str, ...], prompt: str) -> str:
    text = stdout.strip()
    if not text:
        raise ValueError("user CLI returned empty stdout")
    if cli_kind == "codex":
        parsed = parse_codex_exec_jsonl(text, prompt_text=prompt)
        return str(parsed.get("answer", "")).strip()
    if cli_kind == "claude":
        parsed = parse_claude_json_output(text, prompt_text=prompt)
        return str(parsed.get("answer", "")).strip()
    return text


def invoke_user_cli(
    prompt: str,
    *,
    cli_kind: str,
    executable: str,
    cwd: Path,
    timeout_s: float = 60.0,
) -> str:
    """Invoke a production CLI to produce the next user utterance."""
    if cli_kind == "codex":
        argv = [executable, "exec", "--json", prompt]
    elif cli_kind == "claude":
        argv = [executable, "-p", prompt, "--output-format", "json"]
    else:
        raise ValueError(f"unsupported user CLI kind: {cli_kind}")
    result = run_cli(argv, cwd=cwd, timeout_s=timeout_s)
    if result.exit_code != 0:
        raise CliInvocationError(
            f"user CLI exited {result.exit_code}: {result.stderr.strip() or result.stdout.strip()}",
            result=result,
        )
    return _parse_user_cli_text(
        result.stdout,
        cli_kind=cli_kind,
        argv=tuple(argv),
        prompt=prompt,
    )


class CliBackedTaskUser(HalfDuplexUser):
    """Simulate the tau2 user via an installed Codex or Claude CLI."""

    def __init__(
        self,
        task,
        *,
        executable: str,
        cli_kind: str,
        cwd: Path,
        timeout_s: float = 60.0,
    ) -> None:
        super().__init__(instructions=None, tools=None)
        self._task = task
        self._executable = executable
        self._cli_kind = cli_kind
        self._cwd = cwd
        self._timeout_s = timeout_s
        self._sent_scenario = False

    def set_seed(self, seed: int) -> None:
        return None

    def get_init_state(
        self,
        message_history: list | None = None,
    ) -> UserState:
        messages = list(message_history or [])
        return UserState(messages=messages, system_messages=[])

    def _build_prompt(self, assistant_text: str, state: UserState) -> str:
        scenario = _task_reason_for_call(self._task)
        history_lines: list[str] = []
        for message in state.messages:
            if isinstance(message, UserMessage) and message.content:
                history_lines.append(f"user: {message.content}")
            elif isinstance(message, AssistantMessage) and message.content:
                history_lines.append(f"assistant: {message.content}")
        history = "\n".join(history_lines) or "(start)"
        return (
            "You are simulating the customer in a tau2-bench support conversation.\n"
            f"Scenario:\n{scenario}\n\n"
            f"Conversation so far:\n{history}\n\n"
            f"Latest assistant message:\n{assistant_text}\n\n"
            "Reply with only the next user message. Do not act as the assistant."
        )

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
                prompt = self._build_prompt(str(message.content or ""), state)
                content = invoke_user_cli(
                    prompt,
                    cli_kind=self._cli_kind,
                    executable=self._executable,
                    cwd=self._cwd,
                    timeout_s=self._timeout_s,
                )
            user_msg = UserMessage(role="user", content=content)
            state.messages.append(user_msg)
            return user_msg, state
        user_msg = UserMessage(role="user", content="Thanks, that works for me.")
        state.messages.append(user_msg)
        return user_msg, state
