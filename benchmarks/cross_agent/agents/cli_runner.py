"""Shared production agent runner that invokes a real CLI boundary."""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..compatibility import CellImplementation, lookup_matrix_cell
from ..metrics import approximate_token_count
from ..types import AgentKind, AgentOutcome, BenchmarkQuery, BenchmarkRunConfig, MemoryBackendKind
from .cli_parsers import (
    parse_claude_json_output,
    parse_codex_exec_jsonl,
    parse_openclaw_agent_json,
)
from .cli_process import (
    CliInvocationError,
    CliInvocationResult,
    parse_benchmark_json,
    resolve_agent_executable,
    run_cli,
)
from .hm_arch_bench import (
    configure_hm_arch_agent_install,
    hm_arch_cli_env,
    openclaw_benchmark_config_path,
)
from .workspace import AgentWorkspace


@dataclass
class AgentRunnerContext:
    """Per-run state for production agent adapters."""

    workspace: AgentWorkspace
    config: BenchmarkRunConfig
    storage_dir: Path
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
        self._resolved_executable: str | None = None
        self._cli_mode: str | None = None

    @property
    def workspace(self) -> AgentWorkspace:
        return self._context.workspace

    @property
    def config(self) -> BenchmarkRunConfig:
        return self._context.config

    @property
    def storage_dir(self) -> Path:
        return self._context.storage_dir

    def hook_managed_recall(self) -> bool:
        """Return whether HM-Arch hooks own retrieval for this run."""
        return (
            self.config.backend is MemoryBackendKind.HM_ARCH
            and self._cli_mode == "real"
        )

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
        executable = resolve_agent_executable(
            self.agent.value,
            override=self._context.executable,
            default_names=self.default_executable_names,
        )
        if executable is None:
            raise NotImplementedError(
                f"{self.agent.value} CLI executable not found on PATH"
            )
        if self._supports_real_cli(executable):
            self._cli_mode = "real"
        elif self._supports_benchmark_subcommand(executable):
            self._cli_mode = "benchmark"
        else:
            raise NotImplementedError(self._unsupported_cli_message())
        self._resolved_executable = executable
        self._opened = True

    def close(self) -> None:
        if self._opened:
            self._on_close()
            self.workspace.deactivate()
            self._opened = False
            self._resolved_executable = None
            self._cli_mode = None

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
        if not self._opened or self._resolved_executable is None:
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

        executable = self._resolved_executable
        prompt_payload = {
            "context": recalled_context,
            "question": query.question,
            "seed": seed,
            "backend": self.config.backend.value,
            "session_id": self._session_id,
            "query_id": query.query_id,
        }
        argv = self._build_argv(executable, prompt_payload)
        cli_env = hm_arch_cli_env(
            self.storage_dir,
            self.config,
            agent_home=self.workspace.agent_home,
        )
        t0 = time.perf_counter()
        try:
            result = run_cli(
                argv,
                cwd=self.workspace.workspace,
                env=cli_env or None,
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
        prompt_text = self._format_prompt(prompt_payload)
        input_tokens = int(
            parsed.get(
                "input_tokens",
                approximate_token_count(prompt_text),
            )
        )
        output_tokens = int(
            parsed.get(
                "output_tokens",
                approximate_token_count(parsed.get("answer", "")),
            )
        )
        return AgentOutcome(
            answer=str(parsed.get("answer", "")),
            task_success=parsed.get("task_success"),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_token_source=str(parsed.get("input_token_source", "estimated")),
            output_token_source=str(parsed.get("output_token_source", "estimated")),
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
            "hm_arch_db_path": str(self.storage_dir / "hm_arch.db")
            if self.config.backend is MemoryBackendKind.HM_ARCH
            else None,
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
        if parsed is not None:
            metadata["input_token_source"] = parsed.get("input_token_source", "estimated")
            metadata["output_token_source"] = parsed.get("output_token_source", "estimated")
        return metadata

    def _build_benchmark_argv(
        self,
        executable: str,
        prompt_payload: dict[str, Any],
    ) -> list[str]:
        """Argv for offline benchmark CLI doubles used in tests."""
        return [
            executable,
            "hm-arch-benchmark",
            "answer",
            "--json-input",
            json.dumps(prompt_payload, separators=(",", ":")),
        ]

    def _parse_benchmark_response(self, result: CliInvocationResult) -> dict[str, Any]:
        parsed = parse_benchmark_json(result.stdout)
        parsed.setdefault("input_token_source", "exact")
        parsed.setdefault("output_token_source", "exact")
        return parsed

    def _format_prompt(self, payload: dict[str, Any]) -> str:
        context = str(payload.get("context", "")).strip()
        question = str(payload.get("question", "")).strip()
        if context:
            return f"{context}\n\nQuestion: {question}"
        return question

    def _cli_boundary_available(self) -> bool:
        """Return whether a real or test-double CLI boundary is available."""
        if self._resolved_executable is None:
            executable = resolve_agent_executable(
                self.agent.value,
                override=self._context.executable,
                default_names=self.default_executable_names,
            )
            if executable is None:
                return False
            return self._supports_real_cli(executable) or self._supports_benchmark_subcommand(
                executable
            )
        return self._cli_mode in {"real", "benchmark"}

    def _unsupported_cli_message(self) -> str:
        return (
            f"{self.agent.value} production CLI boundary is unavailable: "
            "no supported one-shot invocation or hm-arch-benchmark test double."
        )

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

    @abstractmethod
    def _supports_real_cli(self, executable: str) -> bool:
        """Return whether the installed executable supports the real CLI path."""

    def _build_argv(self, executable: str, prompt_payload: dict[str, Any]) -> list[str]:
        if self._cli_mode == "real":
            return self._build_real_argv(executable, prompt_payload)
        if self._cli_mode == "benchmark":
            return self._build_benchmark_argv(executable, prompt_payload)
        raise RuntimeError("CLI mode was not resolved during open()")

    @abstractmethod
    def _build_real_argv(
        self, executable: str, prompt_payload: dict[str, Any]
    ) -> list[str]:
        """Build argv for the production one-shot CLI boundary."""

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
            configure_hm_arch_agent_install(
                self.agent,
                storage_dir=self.storage_dir,
                workspace=self.workspace.workspace,
                agent_home=self.workspace.agent_home,
            )

    def _on_reset_session(self) -> None:
        return None

    def _on_close(self) -> None:
        return None


class CodexCliAgentRunner(CliAgentRunner):
    agent = AgentKind.CODEX
    kind = "codex-cli"
    default_executable_names = ("codex",)

    def _supports_real_cli(self, executable: str) -> bool:
        try:
            result = run_cli(
                [executable, "exec", "--help"],
                cwd=self.workspace.workspace,
                timeout_s=5.0,
            )
        except CliInvocationError:
            return False
        return result.exit_code == 0

    def _build_real_argv(
        self, executable: str, prompt_payload: dict[str, Any]
    ) -> list[str]:
        prompt = self._format_prompt(prompt_payload)
        argv = [
            executable,
            "exec",
            "--json",
            prompt,
        ]
        if self.config.backend is not MemoryBackendKind.NATIVE_MEMORY:
            argv[3:3] = ["--disable", "memories"]
        return argv

    def _parse_response(
        self,
        result: CliInvocationResult,
        prompt_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if "hm-arch-benchmark" in result.argv:
            return self._parse_benchmark_response(result)
        return parse_codex_exec_jsonl(
            result.stdout,
            prompt_text=self._format_prompt(prompt_payload),
        )


class ClaudeCodeCliAgentRunner(CliAgentRunner):
    agent = AgentKind.CLAUDE_CODE
    kind = "claude-code-cli"
    default_executable_names = ("claude",)

    def _supports_real_cli(self, executable: str) -> bool:
        try:
            result = run_cli(
                [executable, "--help"],
                cwd=self.workspace.workspace,
                timeout_s=5.0,
            )
        except CliInvocationError:
            return False
        combined = f"{result.stdout}\n{result.stderr}"
        return result.exit_code == 0 and "--output-format" in combined

    def _build_real_argv(
        self, executable: str, prompt_payload: dict[str, Any]
    ) -> list[str]:
        prompt = self._format_prompt(prompt_payload)
        return [
            executable,
            "-p",
            prompt,
            "--output-format",
            "json",
        ]

    def _parse_response(
        self,
        result: CliInvocationResult,
        prompt_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if "hm-arch-benchmark" in result.argv:
            return self._parse_benchmark_response(result)
        return parse_claude_json_output(
            result.stdout,
            prompt_text=self._format_prompt(prompt_payload),
        )


class HermesCliAgentRunner(CliAgentRunner):
    agent = AgentKind.HERMES
    kind = "hermes-cli"
    default_executable_names = ("hermes",)

    def _supports_real_cli(self, executable: str) -> bool:
        try:
            result = run_cli(
                [executable, "--help"],
                cwd=self.workspace.workspace,
                timeout_s=5.0,
            )
        except CliInvocationError:
            return False
        combined = f"{result.stdout}\n{result.stderr}"
        return result.exit_code == 0 and ("-z" in combined or "--oneshot" in combined)

    def _build_real_argv(
        self, executable: str, prompt_payload: dict[str, Any]
    ) -> list[str]:
        prompt = self._format_prompt(prompt_payload)
        return [executable, "-z", prompt]

    def _parse_response(
        self,
        result: CliInvocationResult,
        prompt_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if "hm-arch-benchmark" in result.argv:
            return self._parse_benchmark_response(result)
        text = result.stdout.strip()
        return {
            "answer": text,
            "input_tokens": approximate_token_count(self._format_prompt(prompt_payload)),
            "output_tokens": approximate_token_count(text),
            "input_token_source": "estimated",
            "output_token_source": "estimated",
            "runner": "hermes-oneshot",
        }


class OpenClawCliAgentRunner(CliAgentRunner):
    agent = AgentKind.OPENCLAW
    kind = "openclaw-cli"
    default_executable_names = ("openclaw",)

    def _supports_real_cli(self, executable: str) -> bool:
        try:
            result = run_cli(
                [executable, "agent", "--help"],
                cwd=self.workspace.workspace,
                timeout_s=5.0,
            )
        except CliInvocationError:
            return False
        combined = f"{result.stdout}\n{result.stderr}"
        return result.exit_code == 0 and "--message" in combined

    def _build_real_argv(
        self, executable: str, prompt_payload: dict[str, Any]
    ) -> list[str]:
        prompt = self._format_prompt(prompt_payload)
        return [
            executable,
            "agent",
            "--agent",
            "main",
            "--session-key",
            self._session_id,
            "--message",
            prompt,
            "--local",
            "--json",
        ]

    def _parse_response(
        self,
        result: CliInvocationResult,
        prompt_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if "hm-arch-benchmark" in result.argv:
            return self._parse_benchmark_response(result)
        return parse_openclaw_agent_json(
            result.stdout,
            prompt_text=self._format_prompt(prompt_payload),
        )

    def _prepare_agent_home(self) -> None:
        config_path = openclaw_benchmark_config_path(self.workspace.agent_home)
        if self.config.backend is MemoryBackendKind.NO_MEMORY:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            if not config_path.exists():
                config_path.write_text("{}\n", encoding="utf-8")
        super()._prepare_agent_home()
