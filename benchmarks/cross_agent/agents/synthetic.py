"""Offline synthetic agent that answers from recalled context."""

from __future__ import annotations

import re
import time

from ..metrics import approximate_token_count, normalize_answer
from ..types import AgentOutcome, BenchmarkQuery


class SyntheticAgentRunner:
    """Deterministic offline agent for harness lifecycle tests.

  Real OpenClaw/Hermes/Claude Code/Codex adapters register via
  :func:`~benchmarks.cross_agent.agents.register_agent_runner`.
    """

    kind = "synthetic"

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
        return AgentOutcome(
            answer=answer,
            task_success=task_success,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            agent_time_ms=elapsed,
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

        # HotpotQA multi-hop: pick a capitalized place name when present.
        for token in re.findall(r"\b([A-Z][a-z]+)\b", context):
            if token in {"Dr", "The", "Nova", "Science", "Prize", "Orion", "Telescope"}:
                continue
            if query.expected_answer and token.lower() == query.expected_answer.lower():
                return token

        return "unknown"
