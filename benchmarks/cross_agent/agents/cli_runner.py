"""Shared production agent runner that invokes a real CLI boundary."""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from hm_arch.integrations.executable import resolve_hm_arch_command_prefix

from ..compatibility import CellImplementation, lookup_matrix_cell
from ..metrics import approximate_token_count
from ..types import AgentKind, AgentOutcome, BenchmarkQuery, BenchmarkRunConfig, MemoryBackendKind
from .cli_process import (
    CliInvocationError,
    CliInvocationResult,
    parse_benchmark_json,
    resolve_agent_executable,
    run_cli,
)
from .workspace import AgentWorkspace


@dataclass
class AgentRunnerContext:
    """Per-run state for production agent adapters."""

    workspace: AgentWorkspace
    config: BenchmarkRunConfig
    executable: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class CliAgentRunner(ABC):
    """Invoke a host agent through its CLI with isolated home and timeout."""

    agent: AgentKind
    kind: str = "cli"
    implementation = CellImplementation.REAL
    default_executable_names: tuple[str, ...] = ()

    def __init__(self, context: AgentRunnerContext) -> None:
        self._context = context
        self._opened = False
        self._session_id = f"bench-{context.workspace.run_id}"
        self._last_invocation: CliInvocationResult | None = None

    @property
    def workspace(self) -> AgentWorkspace:
        return self._context.workspace

    @property
    def config(self) -> BenchmarkRunConfig:
        return self._context.config

    def open(self) -> None:
        cell = lookup_matrix_cell(self.config.agent, self.config.backend)
        if cell.implementation is CellImplementation.UNSUPPORTED:
            raise NotImplementedError(cell.rationale)
        if self.config.use_mock_agent:
            raise RuntimeError(
                f"{self.agent.value} CLI runner cannot run with use_mock_agent=True"
            )
        self.workspace.activate()
        self._prepare_agent_home()
        self._opened = True

    def close(self) -> None:
        if self._opened:
            self._on_close()
            self.workspace.deactivate()
            self._opened = False

    def reset_session(self) -> None:
        """Reset agent session state without tearing down the workspace."""
        self._on_reset_session()

    def answer(
        self,
        query: BenchmarkQuery,
        *,
        recalled_context: str,
        seed: int,
    ) -> AgentOutcome:
        if not self._opened:
            return AgentOutcome(
                answer="",
                task_success=None,
                input_tokens=0,
                output_tokens=0,
                agent_time_ms=0.0,
                failure_count=1,
                error="Agent runner open() was not called",
                metadata={"runner_mode": self.implementation.value},
            )

        executable = resolve_agent_executable(
            self.agent.value,
            override=self._context.executable,
            default_names=self.default_executable_names,
        )
        if executable is None:
            return AgentOutcome(
                answer="",
                task_success=None,
                input_tokens=0,
                output_tokens=0,
                agent_time_ms=0.0,
                failure_count=1,
                error=f"{self.agent.value} CLI executable not found on PATH",
                metadata={
                    "runner_mode": self.implementation.value,
                    "backend": self.config.backend.value,
                },
            )

        prompt_payload = {
            "context": recalled_context,
            "question": query.question,
            "seed": seed,
            "backend": self.config.backend.value,
            "session_id": self._session_id,
            "query_id": query.query_id,
        }
        argv = self._build_argv(executable, prompt_payload)
        t0 = time.perf_counter()
        try:
            result = run_cli(
                argv,
                cwd=self.workspace.workspace,
                timeout_s=self.config.agent_timeout_s,
            )
            self._last_invocation = result
            if result.exit_code != 0:
                return self._failure_outcome(
                    f"CLI exited {result.exit_code}: {result.stderr.strip() or result.stdout.strip()}",
                    result,
                    started_at=t0,
                )
            parsed = self._parse_response(result, prompt_payload)
        except CliInvocationError as exc:
            self._last_invocation = exc.result
            return self._failure_outcome(str(exc), exc.result, started_at=t0)
        except Exception as exc:  # noqa: BLE001 — benchmark must capture agent failures
            elapsed = (time.perf_counter() - t0) * 1000.0
            return AgentOutcome(
                answer="",
                task_success=None,
                input_tokens=0,
                output_tokens=0,
                agent_time_ms=elapsed,
                failure_count=1,
                error=str(exc),
                metadata=self._outcome_metadata(None, prompt_payload),
            )

        elapsed = (time.perf_counter() - t0) * 1000.0
        input_tokens = int(parsed.get("input_tokens", approximate_token_count(
            f"{recalled_context}\n{query.question}"
        )))
        output_tokens = int(parsed.get("output_tokens", approximate_token_count(parsed.get("answer", ""))))
        return AgentOutcome(
            answer=str(parsed.get("answer", "")),
            task_success=parsed.get("task_success"),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            agent_time_ms=elapsed,
            failure_count=0,
            metadata=self._outcome_metadata(result, prompt_payload, parsed),
        )

    def _failure_outcome(
        self,
        message: str,
        result: CliInvocationResult | None,
        *,
        started_at: float,
    ) -> AgentOutcome:
        elapsed = (time.perf_counter() - started_at) * 1000.0
        metadata = {
            "runner_mode": self.implementation.value,
            "backend": self.config.backend.value,
        }
        if result is not None:
            metadata.update(
                {
                    "exit_code": result.exit_code,
                    "stderr": result.stderr,
                    "stdout": result.stdout,
                    "argv": list(result.argv),
                    "timed_out": result.timed_out,
                }
            )
        return AgentOutcome(
            answer="",
            task_success=None,
            input_tokens=0,
            output_tokens=0,
            agent_time_ms=elapsed,
            failure_count=1,
            error=message,
            metadata=metadata,
        )

    def _outcome_metadata(
        self,
        result: CliInvocationResult | None,
        prompt_payload: dict[str, Any],
        parsed: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "runner_mode": self.implementation.value,
            "backend": self.config.backend.value,
            "memory_mode": self.config.backend.value,
            "agent_home": str(self.workspace.agent_home),
            "workspace_root": str(self.workspace.root),
            "session_id": self._session_id,
            "prompt_payload_keys": sorted(prompt_payload),
        }
        if result is not None:
            metadata["exit_code"] = result.exit_code
            metadata["argv"] = list(result.argv)
            if result.stderr.strip():
                metadata["stderr"] = result.stderr
        if parsed is not None and parsed.get("runner"):
            metadata["cli_runner"] = parsed["runner"]
        return metadata

    def _build_benchmark_argv(
        self,
        executable: str,
        prompt_payload: dict[str, Any],
    ) -> list[str]:
        """Default argv for fake/offline benchmark CLIs."""
        return [
            executable,
            "hm-arch-benchmark",
            "answer",
            "--json-input",
            json.dumps(prompt_payload, separators=(",", ":")),
        ]

    def _parse_benchmark_response(self, result: CliInvocationResult) -> dict[str, Any]:
        return parse_benchmark_json(result.stdout)

    @abstractmethod
    def _build_argv(self, executable: str, prompt_payload: dict[str, Any]) -> list[str]:
        """Build the argv vector for this agent."""

    def _parse_response(
        self,
        result: CliInvocationResult,
        prompt_payload: dict[str, Any],
    ) -> dict[str, Any]:
        del prompt_payload
        return self._parse_benchmark_response(result)

    def _prepare_agent_home(self) -> None:
        """Install hooks or provider config when backend requires external memory."""
        if self.config.backend is MemoryBackendKind.HM_ARCH:
            self._install_hm_arch_integration()

    def _install_hm_arch_integration(self) -> None:
        prefix = resolve_hm_arch_command_prefix()
        if self.agent is AgentKind.CODEX:
            from hm_arch.integrations.codex.installer import InstallScope, install_codex

            install_codex(InstallScope.PROJECT, project_root=self.workspace.workspace)
        elif self.agent is AgentKind.CLAUDE_CODE:
            from hm_arch.integrations.claude_code.installer import (
                InstallScope,
                install_claude_code,
            )

            install_claude_code(InstallScope.PROJECT, project_root=self.workspace.workspace)
        elif self.agent is AgentKind.HERMES:
            from hm_arch.integrations.management.hermes import HermesAgentHandler

            HermesAgentHandler().install(global_install=False)
        elif self.agent is AgentKind.OPENCLAW:
            from hm_arch.integrations.management.openclaw import OpenClawAgentHandler

            OpenClawAgentHandler().install(global_install=False)
        else:
            raise ValueError(f"unsupported agent for HM-Arch install: {self.agent}")
        _ = prefix

    def _on_reset_session(self) -> None:
        return None

    def _on_close(self) -> None:
        return None


class CodexCliAgentRunner(CliAgentRunner):
    agent = AgentKind.CODEX
    kind = "codex-cli"
    default_executable_names = ("codex",)

    def _build_argv(self, executable: str, prompt_payload: dict[str, Any]) -> list[str]:
        if self._supports_benchmark_subcommand(executable):
            return self._build_benchmark_argv(executable, prompt_payload)
        prompt = self._format_prompt(prompt_payload)
        return [
            executable,
            "exec",
            "--json",
            "--disable",
            "memories",
            prompt,
        ]

    def _supports_benchmark_subcommand(self, executable: str) -> bool:
        try:
            result = run_cli(
                [executable, "hm-arch-benchmark", "--help"],
                cwd=self.workspace.workspace,
                timeout_s=5.0,
            )
        except CliInvocationError:
            return False
        return result.exit_code == 0

    def _format_prompt(self, payload: dict[str, Any]) -> str:
        context = str(payload.get("context", "")).strip()
        question = str(payload.get("question", "")).strip()
        if context:
            return f"{context}\n\nQuestion: {question}"
        return question

    def _parse_response(
        self,
        result: CliInvocationResult,
        prompt_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if "hm-arch-benchmark" in result.argv:
            return self._parse_benchmark_response(result)
        text = result.stdout.strip()
        try:
            payload = json.loads(text)
            if isinstance(payload, dict) and "answer" in payload:
                return payload
        except json.JSONDecodeError:
            pass
        return {
            "answer": text,
            "input_tokens": approximate_token_count(
                f"{prompt_payload.get('context', '')}\n{prompt_payload.get('question', '')}"
            ),
            "output_tokens": approximate_token_count(text),
            "runner": "codex-exec",
        }


class ClaudeCodeCliAgentRunner(CliAgentRunner):
    agent = AgentKind.CLAUDE_CODE
    kind = "claude-code-cli"
    default_executable_names = ("claude",)

    def _build_argv(self, executable: str, prompt_payload: dict[str, Any]) -> list[str]:
        if self._supports_benchmark_subcommand(executable):
            return self._build_benchmark_argv(executable, prompt_payload)
        prompt = self._format_prompt(prompt_payload)
        return [
            executable,
            "-p",
            prompt,
            "--output-format",
            "json",
        ]

    def _supports_benchmark_subcommand(self, executable: str) -> bool:
        try:
            result = run_cli(
                [executable, "hm-arch-benchmark", "--help"],
                cwd=self.workspace.workspace,
                timeout_s=5.0,
            )
        except CliInvocationError:
            return False
        return result.exit_code == 0

    def _format_prompt(self, payload: dict[str, Any]) -> str:
        context = str(payload.get("context", "")).strip()
        question = str(payload.get("question", "")).strip()
        if context:
            return f"{context}\n\nQuestion: {question}"
        return question

    def _parse_response(
        self,
        result: CliInvocationResult,
        prompt_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if "hm-arch-benchmark" in result.argv:
            return self._parse_benchmark_response(result)
        text = result.stdout.strip()
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                answer = payload.get("result") or payload.get("answer") or text
                return {
                    "answer": str(answer),
                    "input_tokens": payload.get("input_tokens"),
                    "output_tokens": payload.get("output_tokens"),
                    "runner": "claude-json",
                }
        except json.JSONDecodeError:
            pass
        return {
            "answer": text,
            "input_tokens": approximate_token_count(
                f"{prompt_payload.get('context', '')}\n{prompt_payload.get('question', '')}"
            ),
            "output_tokens": approximate_token_count(text),
            "runner": "claude-text",
        }


class HermesCliAgentRunner(CliAgentRunner):
    agent = AgentKind.HERMES
    kind = "hermes-cli"
    default_executable_names = ("hermes",)

    def _build_argv(self, executable: str, prompt_payload: dict[str, Any]) -> list[str]:
        return self._build_benchmark_argv(executable, prompt_payload)


class OpenClawCliAgentRunner(CliAgentRunner):
    agent = AgentKind.OPENCLAW
    kind = "openclaw-cli"
    default_executable_names = ("openclaw",)

    def _build_argv(self, executable: str, prompt_payload: dict[str, Any]) -> list[str]:
        return self._build_benchmark_argv(executable, prompt_payload)

    def _prepare_agent_home(self) -> None:
        config_path = self.workspace.workspace / ".openclaw" / "openclaw.json"
        if self.config.backend is MemoryBackendKind.NO_MEMORY:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            if not config_path.exists():
                config_path.write_text("{}\n", encoding="utf-8")
        super()._prepare_agent_home()
