"""Offline mock agent runner (explicit test double only)."""

from __future__ import annotations

import re
import time

from ..compatibility import CellImplementation
from ..metrics import approximate_token_count, normalize_answer
from ..types import AgentOutcome, BenchmarkQuery, BenchmarkRunConfig
from .workspace import AgentWorkspace


class MockSyntheticAgentRunner:
    """Deterministic offline mock for harness lifecycle tests.

    This is **not** a production OpenClaw/Hermes/Claude Code/Codex adapter.
    Register production CLI runners via
    :func:`~benchmarks.cross_agent.agents.registry.create_agent_runner`.
    """

    kind = "mock-synthetic"
    implementation = CellImplementation.MOCK_ONLY

    def __init__(
        self,
        workspace: AgentWorkspace | None = None,
        config: BenchmarkRunConfig | None = None,
    ) -> None:
        self._workspace = workspace
        self._config = config
        self._opened = False

    def open(self) -> None:
        self._opened = True

    def close(self) -> None:
        self._opened = False

    def reset_session(self) -> None:
        return None

    def answer(
        self,
        query: BenchmarkQuery,
        *,
        recalled_context: str,
        seed: int,
    ) -> AgentOutcome:
        _ = seed
        t0 = time.perf_counter()
        prompt = f"{recalled_context}\n\nQuestion: {query.question}"
        input_tokens = approximate_token_count(prompt)

        answer = self._extract_answer(query, recalled_context)
        output_tokens = approximate_token_count(answer)

        task_success: bool | None = None
        if query.task_success_criteria is not None:
            haystack = normalize_answer(recalled_context)
            task_success = normalize_answer(query.task_success_criteria) in haystack

        elapsed = (time.perf_counter() - t0) * 1000.0
        metadata = {
            "runner_mode": self.implementation.value,
            "backend": self._config.backend.value if self._config else None,
        }
        if self._config is not None:
            metadata["memory_mode"] = self._config.backend.value
        if self._workspace is not None:
            metadata["agent_home"] = str(self._workspace.agent_home)
        return AgentOutcome(
            answer=answer,
            task_success=task_success,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            agent_time_ms=elapsed,
            metadata=metadata,
        )

    def _extract_answer(self, query: BenchmarkQuery, context: str) -> str:
        if query.expected_answer and normalize_answer(query.expected_answer) in normalize_answer(
            context
        ):
            return query.expected_answer

        if query.task_success_criteria:
            match = re.search(r"Reason:\s*([^.]+)", context, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
            if "completed" in context.lower():
                return "yes"
            if "failed" in context.lower():
                return "failed"

        for token in re.findall(r"\b([A-Z][a-z]+)\b", context):
            if token in {"Dr", "The", "Nova", "Science", "Prize", "Orion", "Telescope"}:
                continue
            if query.expected_answer and token.lower() == query.expected_answer.lower():
                return token

        return "unknown"


# Backward-compatible alias used by existing harness tests.
SyntheticAgentRunner = MockSyntheticAgentRunner
