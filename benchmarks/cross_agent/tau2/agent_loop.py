"""Run tau2-bench tasks with external agent CLIs driving tool calls."""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..agents.cli_process import (
    CliInvocationError,
    CliInvocationResult,
    resolve_agent_executable,
    run_cli,
)
from ..agents.cli_runner import (
    AgentRunnerContext,
    ClaudeCodeCliAgentRunner,
    CodexCliAgentRunner,
    HermesCliAgentRunner,
    OpenClawCliAgentRunner,
)
from ..agents.hm_arch_bench import agent_prompt_context, hm_arch_cli_env
from ..agents.workspace import AgentWorkspace
from ..metrics import approximate_token_count
from ..types import AgentKind, BenchmarkRunConfig, MemoryBackendKind
from .agent_cli import is_harness_executable
from .availability import require_tau2
from .config import Tau2Domain
from .cli_user import CliBackedTaskUser, resolve_user_cli_executable
from .loader import _task_reason_for_call
from .scripted_user import ScriptedTaskUser
from .tool_prompt import format_tool_signatures

HARNESS_AGENT_LABEL = "tau2_gold_action_harness"
REAL_AGENT_LOOP_LABEL = "tau2_agent_environment_loop"


@dataclass(frozen=True)
class Tau2AgentStepRecord:
    """One agent turn in the tau2 environment loop."""

    step_index: int
    observation: str
    action: str
    argv: tuple[str, ...]
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: float
    input_tokens: int
    output_tokens: int
    input_token_source: str
    output_token_source: str
    terminated: bool
    reward: float | None = None
    error: str | None = None


@dataclass
class Tau2AgentTaskExecution:
    """Outcome of one tau2 task executed via the agent-environment loop."""

    domain: Tau2Domain
    task_id: str
    reward: float | None
    task_success: bool
    steps: list[Tau2AgentStepRecord] = field(default_factory=list)
    simulation_messages: list[dict[str, Any]] = field(default_factory=list)
    evaluation: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    error: str | None = None
    harness_label: str | None = None
    agent_executable: str | None = None
    agent_invocation_mode: str | None = None
    user_mode: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain.value,
            "task_id": self.task_id,
            "reward": self.reward,
            "task_success": self.task_success,
            "steps": [
                {
                    "step_index": step.step_index,
                    "observation": step.observation,
                    "action": step.action,
                    "argv": list(step.argv),
                    "stdout": step.stdout,
                    "stderr": step.stderr,
                    "exit_code": step.exit_code,
                    "duration_ms": step.duration_ms,
                    "input_tokens": step.input_tokens,
                    "output_tokens": step.output_tokens,
                    "input_token_source": step.input_token_source,
                    "output_token_source": step.output_token_source,
                    "terminated": step.terminated,
                    "reward": step.reward,
                    "error": step.error,
                }
                for step in self.steps
            ],
            "simulation_messages": self.simulation_messages,
            "evaluation": self.evaluation,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "harness_label": self.harness_label,
            "agent_executable": self.agent_executable,
            "agent_invocation_mode": self.agent_invocation_mode,
            "user_mode": self.user_mode,
        }


def _format_observation(messages: list) -> str:
    from tau2.data_model.message import AssistantMessage, UserMessage
    from tau2.utils.tools import to_functional_format

    if not messages:
        return ""
    turns: list[str] = []
    for message in messages:
        if isinstance(message, UserMessage):
            if not message.is_tool_call():
                turns.append(f"user: {message.content}")
            else:
                tool_calls = ", ".join(to_functional_format(tool) for tool in message.tool_calls)
                turns.append(f"user: {tool_calls}")
        elif isinstance(message, AssistantMessage):
            if not message.is_tool_call():
                turns.append(f"assistant: {message.content}")
            else:
                tool_calls = ", ".join(to_functional_format(tool) for tool in message.tool_calls)
                turns.append(f"assistant: {tool_calls}")
            turns = []
        else:
            turns.append(f"{message.role}: {getattr(message, 'content', '')}")
    return "\n".join(turns)


def _build_tau2_prompt(
    *,
    domain: Tau2Domain,
    task,
    observation: str,
    policy: str,
    tools: list,
    memory_context: str,
    step_index: int,
) -> str:
    tool_block = format_tool_signatures(tools)
    memory_block = memory_context.strip() or "(none)"
    return (
        f"You are executing tau2-bench domain={domain.value} task_id={task.id} "
        f"step={step_index}.\n\n"
        f"Policy:\n{policy}\n\n"
        f"Task reason for call:\n{_task_reason_for_call(task)}\n\n"
        f"Recalled memory:\n{memory_block}\n\n"
        f"Available tools:\n{tool_block}\n\n"
        f"Conversation observation:\n{observation or '(start)'}\n\n"
        "Respond with exactly one action string:\n"
        "- functional tool call, e.g. find_user_id_by_name_zip(first_name='A', last_name='B', zip='12345')\n"
        "- plain text to reply to the user\n"
        "- done() when the task is complete\n"
    )


def _parse_cli_action(stdout: str, *, agent: AgentKind, argv: tuple[str, ...]) -> str:
    text = stdout.strip()
    if not text:
        raise ValueError("agent CLI returned empty stdout")
    if agent is AgentKind.CODEX and "exec" in argv:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if payload.get("type") == "item.completed":
                item = payload.get("item") or {}
                if item.get("type") == "agent_message":
                    return str(item.get("text", "")).strip()
        raise ValueError("codex exec JSONL did not contain agent_message")
    if agent is AgentKind.CLAUDE_CODE and "--output-format" in argv:
        payload = json.loads(text)
        return str(payload.get("result", "")).strip()
    if "hm-arch-benchmark" in argv and "tau2-step" in argv:
        payload = json.loads(text)
        return str(payload.get("action", "")).strip()
    return text


def _resolve_cli_runner(agent: AgentKind, context: AgentRunnerContext):
    runners = {
        AgentKind.CODEX: CodexCliAgentRunner,
        AgentKind.CLAUDE_CODE: ClaudeCodeCliAgentRunner,
        AgentKind.HERMES: HermesCliAgentRunner,
        AgentKind.OPENCLAW: OpenClawCliAgentRunner,
    }
    runner_cls = runners.get(agent)
    if runner_cls is None:
        raise NotImplementedError(f"No tau2 CLI runner for agent {agent.value}")
    return runner_cls(context)


def _invoke_agent_cli(
    *,
    agent: AgentKind,
    config: BenchmarkRunConfig,
    workspace: AgentWorkspace,
    storage_dir: Path,
    executable: str,
    prompt: str,
    timeout_s: float,
    harness_payload: dict[str, Any] | None = None,
) -> tuple[str, CliInvocationResult, int, int, str, str]:
    if harness_payload is not None:
        argv = [
            executable,
            "hm-arch-benchmark",
            "tau2-step",
            "--json-input",
            json.dumps(harness_payload, separators=(",", ":")),
        ]
        cli_env = hm_arch_cli_env(
            storage_dir,
            config,
            agent_home=workspace.agent_home,
        )
        result = run_cli(
            argv,
            cwd=workspace.workspace,
            env=cli_env or None,
            timeout_s=timeout_s,
        )
        if result.exit_code != 0:
            raise CliInvocationError(
                f"Harness CLI exited {result.exit_code}",
                result=result,
            )
        action = _parse_cli_action(result.stdout, agent=agent, argv=tuple(argv))
        input_tokens = int(harness_payload.get("prompt_token_estimate", 0))
        output_tokens = approximate_token_count(action)
        return action, result, input_tokens, output_tokens, "exact", "estimated"

    cli_config = config
    if config.use_mock_agent:
        cli_config = BenchmarkRunConfig(
            family=config.family,
            agent=config.agent,
            backend=config.backend,
            seed=config.seed,
            top_k=config.top_k,
            resume=config.resume,
            use_mock_agent=False,
            agent_executable=config.agent_executable,
            agent_timeout_s=config.agent_timeout_s,
        )
    context = AgentRunnerContext(
        workspace=workspace,
        config=cli_config,
        storage_dir=storage_dir,
        executable=executable,
    )
    runner = _resolve_cli_runner(agent, context)
    runner.open()
    try:
        prompt_payload = {
            "context": "",
            "question": prompt,
            "seed": cli_config.seed,
            "backend": cli_config.backend.value,
            "session_id": workspace.run_id,
            "query_id": f"tau2-{workspace.run_id}",
        }
        argv = runner._build_argv(executable, prompt_payload)
        cli_env = hm_arch_cli_env(
            storage_dir,
            cli_config,
            agent_home=workspace.agent_home,
        )
        result = run_cli(
            argv,
            cwd=workspace.workspace,
            env=cli_env or None,
            timeout_s=timeout_s,
        )
        if result.exit_code != 0:
            raise CliInvocationError(
                f"Agent CLI exited {result.exit_code}: {result.stderr.strip() or result.stdout.strip()}",
                result=result,
            )
        parsed = runner._parse_response(result, prompt_payload)
        action = str(parsed.get("answer", "")).strip()
        if not action:
            action = _parse_cli_action(result.stdout, agent=agent, argv=tuple(argv))
        input_tokens = int(parsed.get("input_tokens", approximate_token_count(prompt)))
        output_tokens = int(parsed.get("output_tokens", approximate_token_count(action)))
        input_source = str(parsed.get("input_token_source", "estimated"))
        output_source = str(parsed.get("output_token_source", "estimated"))
        return action, result, input_tokens, output_tokens, input_source, output_source
    finally:
        runner.close()


class _Tau2CliAgentLoop:
    """Drive tau2 Orchestrator + GymAgent with external CLI actions."""

    def __init__(
        self,
        *,
        domain: Tau2Domain,
        task,
        agent: AgentKind,
        config: BenchmarkRunConfig,
        workspace: AgentWorkspace,
        storage_dir: Path,
        executable: str,
        memory_context: str = "",
        use_harness_agent: bool = False,
        user_mode: str = "scripted",
        user_llm: str | None = None,
        user_cli: str = "auto",
        user_cli_executable: str | None = None,
        max_steps: int = 100,
        timeout_s: float = 120.0,
    ) -> None:
        require_tau2()
        from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
        from tau2.gym.gym_agent import GymAgent
        from tau2.orchestrator.orchestrator import Orchestrator
        from tau2.runner.build import build_environment
        from tau2.user.user_simulator import UserSimulator
        from tau2.utils.tools import parse_action_string

        self._domain = domain.value
        self._task = task
        self._agent_kind = agent
        self._config = config
        self._workspace = workspace
        self._storage_dir = storage_dir
        self._executable = executable
        self._memory_context = memory_context
        self._use_harness_agent = use_harness_agent
        self._user_mode = user_mode
        self._user_llm = user_llm
        self._user_cli = user_cli
        self._user_cli_executable = user_cli_executable
        self._max_steps = max_steps
        self._timeout_s = timeout_s
        self._parse_action_string = parse_action_string
        self._evaluate_simulation = evaluate_simulation
        self._EvaluationType = EvaluationType

        environment = build_environment(self._domain, solo_mode=False)
        tools = list(environment.get_tools())
        user_tools = (
            list(environment.get_user_tools(include=task.user_tools))
            if environment.user_tools
            else None
        )
        self._environment = environment
        self._policy = environment.get_policy()
        self._tools = tools
        self._gym_agent = GymAgent(tools=tools, domain_policy=self._policy)
        if user_mode == "llm":
            self._user = UserSimulator(
                tools=user_tools,
                instructions=task.user_scenario,
                llm=user_llm,
            )
        elif user_mode == "cli":
            user_executable, user_cli_kind = resolve_user_cli_executable(
                preference=user_cli,
                override=user_cli_executable,
            )
            if user_executable is None or user_cli_kind is None:
                raise NotImplementedError(
                    "CLI user simulator requires codex or claude on PATH "
                    "(or --user-cli-executable)"
                )
            self._user = CliBackedTaskUser(
                task,
                executable=user_executable,
                cli_kind=user_cli_kind,
                cwd=workspace.workspace,
                timeout_s=timeout_s,
            )
        else:
            self._user = ScriptedTaskUser(task)
        self._orchestrator = Orchestrator(
            domain=self._domain,
            agent=self._gym_agent,
            user=self._user,
            environment=environment,
            task=task,
            max_steps=max_steps,
            solo_mode=False,
            simulation_id=f"hm-arch-{uuid.uuid4().hex[:12]}",
        )
        self._simulation_done = threading.Event()
        self._simulation_run = None
        self._thread: threading.Thread | None = None

    def _run_orchestrator(self) -> None:
        try:
            self._simulation_run = self._orchestrator.run()
        finally:
            self._simulation_done.set()

    def run(self) -> Tau2AgentTaskExecution:
        execution = Tau2AgentTaskExecution(
            domain=Tau2Domain(self._domain),
            task_id=str(self._task.id),
            reward=None,
            task_success=False,
            harness_label=HARNESS_AGENT_LABEL if self._use_harness_agent else None,
            agent_executable=self._executable,
            agent_invocation_mode=(
                "harness_gold_actions" if self._use_harness_agent else REAL_AGENT_LOOP_LABEL
            ),
            user_mode=self._user_mode,
        )
        t0 = time.perf_counter()
        gold_actions = list(self._task.evaluation_criteria.actions or [])
        try:
            self._thread = threading.Thread(target=self._run_orchestrator, daemon=True)
            self._thread.start()

            step_index = 0
            while not self._simulation_done.is_set() and step_index < self._max_steps:
                if not self._gym_agent.is_agent_turn:
                    self._simulation_done.wait(timeout=0.05)
                    continue

                observation = _format_observation(self._gym_agent.observation)
                harness_payload = None
                if self._use_harness_agent:
                    harness_payload = {
                        "domain": self._domain,
                        "task_id": str(self._task.id),
                        "step_index": step_index,
                        "observation": observation,
                        "policy": self._policy,
                        "tools": [tool.name for tool in self._tools],
                        "gold_actions": [
                            {
                                "name": action.name,
                                "arguments": dict(action.arguments or {}),
                                "requestor": action.requestor,
                            }
                            for action in gold_actions
                        ],
                        "prompt_token_estimate": approximate_token_count(observation),
                    }
                    prompt = ""
                else:
                    effective_memory = agent_prompt_context(
                        self._config,
                        self._memory_context,
                        hook_managed=(
                            self._config.backend is MemoryBackendKind.HM_ARCH
                            and not self._use_harness_agent
                            and not is_harness_executable(self._executable)
                        ),
                    )
                    prompt = _build_tau2_prompt(
                        domain=Tau2Domain(self._domain),
                        task=self._task,
                        observation=observation,
                        policy=self._policy,
                        tools=self._tools,
                        memory_context=effective_memory,
                        step_index=step_index,
                    )

                step_t0 = time.perf_counter()
                try:
                    action, result, input_tokens, output_tokens, input_source, output_source = (
                        _invoke_agent_cli(
                            agent=self._agent_kind,
                            config=self._config,
                            workspace=self._workspace,
                            storage_dir=self._storage_dir,
                            executable=self._executable,
                            prompt=prompt,
                            timeout_s=self._timeout_s,
                            harness_payload=harness_payload,
                        )
                    )
                    action_msg = self._parse_action_string(action)
                    self._gym_agent.set_action(action_msg)
                except Exception as exc:  # noqa: BLE001
                    elapsed = (time.perf_counter() - step_t0) * 1000.0
                    execution.steps.append(
                        Tau2AgentStepRecord(
                            step_index=step_index,
                            observation=observation,
                            action="",
                            argv=(),
                            stdout="",
                            stderr=str(exc),
                            exit_code=1,
                            duration_ms=elapsed,
                            input_tokens=0,
                            output_tokens=0,
                            input_token_source="estimated",
                            output_token_source="estimated",
                            terminated=True,
                            error=str(exc),
                        )
                    )
                    execution.error = str(exc)
                    break

                elapsed = (time.perf_counter() - step_t0) * 1000.0
                execution.steps.append(
                    Tau2AgentStepRecord(
                        step_index=step_index,
                        observation=observation,
                        action=action,
                        argv=tuple(result.argv),
                        stdout=result.stdout,
                        stderr=result.stderr,
                        exit_code=result.exit_code,
                        duration_ms=elapsed,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        input_token_source=input_source,
                        output_token_source=output_source,
                        terminated=self._simulation_done.is_set(),
                    )
                )
                step_index += 1
                if self._simulation_done.is_set():
                    break

            if self._thread is not None:
                self._thread.join(timeout=5.0)

            simulation = self._simulation_run
            if simulation is not None:
                execution.simulation_messages = [
                    message.model_dump() for message in (simulation.messages or [])
                ]
                eval_type = self._EvaluationType.ALL
                if self._use_harness_agent or self._user_mode == "scripted":
                    eval_type = self._EvaluationType.ENV
                try:
                    evaluation = self._evaluate_simulation(
                        simulation=simulation,
                        task=self._task,
                        evaluation_type=eval_type,
                        solo_mode=False,
                        domain=self._domain,
                    )
                except ValueError as exc:
                    if "NL assertions" in str(exc):
                        evaluation = self._evaluate_simulation(
                            simulation=simulation,
                            task=self._task,
                            evaluation_type=self._EvaluationType.ENV,
                            solo_mode=False,
                            domain=self._domain,
                        )
                    else:
                        raise
                execution.reward = float(evaluation.reward or 0.0)
                execution.task_success = execution.reward >= 1.0
                execution.evaluation = evaluation.model_dump()
        except Exception as exc:  # noqa: BLE001
            execution.error = str(exc)
        execution.duration_ms = (time.perf_counter() - t0) * 1000.0
        return execution


def run_task_agent_loop(
    domain: Tau2Domain,
    task,
    *,
    agent: AgentKind,
    config: BenchmarkRunConfig,
    workspace: AgentWorkspace,
    storage_dir: Path,
    executable: str | None = None,
    memory_context: str = "",
    use_harness_agent: bool = False,
    user_mode: str = "scripted",
    user_llm: str | None = None,
    user_cli: str = "auto",
    user_cli_executable: str | None = None,
    max_steps: int = 100,
    timeout_s: float = 120.0,
) -> Tau2AgentTaskExecution:
    """Execute one tau2 task with agent-produced tool calls."""
    if use_harness_agent and executable and not is_harness_executable(executable):
        raise ValueError("HARNESS mode requires a labeled fake tau2 CLI executable")
    if not use_harness_agent and is_harness_executable(executable):
        raise ValueError("REAL mode cannot use harness or fake agent executables")

    default_names = {
        AgentKind.CODEX: ("codex",),
        AgentKind.CLAUDE_CODE: ("claude",),
        AgentKind.HERMES: ("hermes",),
        AgentKind.OPENCLAW: ("openclaw",),
    }.get(agent, ())
    resolved = resolve_agent_executable(
        agent.value,
        override=executable,
        default_names=default_names,
    )
    if resolved is None:
        raise NotImplementedError(f"{agent.value} CLI executable not found")
    loop = _Tau2CliAgentLoop(
        domain=domain,
        task=task,
        agent=agent,
        config=config,
        workspace=workspace,
        storage_dir=storage_dir,
        executable=resolved,
        memory_context=memory_context,
        use_harness_agent=use_harness_agent,
        user_mode=user_mode,
        user_llm=user_llm,
        user_cli=user_cli,
        user_cli_executable=user_cli_executable,
        max_steps=max_steps,
        timeout_s=timeout_s,
    )
    return loop.run()


def run_domain_agent_loop(
    domain: Tau2Domain,
    tasks: list,
    *,
    agent: AgentKind,
    config: BenchmarkRunConfig,
    workspace: AgentWorkspace,
    storage_dir: Path,
    backend,
    executable: str | None = None,
    use_harness_agent: bool = False,
    user_mode: str = "scripted",
    user_llm: str | None = None,
    user_cli: str = "auto",
    user_cli_executable: str | None = None,
    max_steps: int = 100,
    timeout_s: float = 120.0,
) -> list[Tau2AgentTaskExecution]:
    """Run each task with a fresh environment reset; memory may carry across tasks."""
    from ..types import BenchmarkQuery, IngestItem

    executions: list[Tau2AgentTaskExecution] = []
    for task in tasks:
        recall_query = BenchmarkQuery(
            query_id=f"{domain.value}-task-{task.id}-recall",
            question=_task_reason_for_call(task),
            metadata={"domain": domain.value, "tau2_task_id": str(task.id)},
        )
        recalled = backend.recall(recall_query, top_k=config.top_k)
        hook_managed = (
            config.backend is MemoryBackendKind.HM_ARCH
            and not use_harness_agent
            and not is_harness_executable(executable)
        )
        memory_context = agent_prompt_context(
            config,
            recalled.context,
            hook_managed=hook_managed,
        )
        execution = run_task_agent_loop(
            domain,
            task,
            agent=agent,
            config=config,
            workspace=workspace,
            storage_dir=storage_dir,
            executable=executable,
            memory_context=memory_context,
            use_harness_agent=use_harness_agent,
            user_mode=user_mode,
            user_llm=user_llm,
            user_cli=user_cli,
            user_cli_executable=user_cli_executable,
            max_steps=max_steps,
            timeout_s=timeout_s,
        )
        executions.append(execution)
        backend.ingest(
            IngestItem(
                item_id=f"{domain.value}-task-{task.id}",
                content=(
                    f"tau2 {domain.value} task {task.id}: "
                    f"success={execution.task_success} reward={execution.reward}"
                ),
                session_id=f"{domain.value}-agent-loop",
                metadata={
                    "domain": domain.value,
                    "tau2_task_id": str(task.id),
                    "tau2_reward": execution.reward,
                    "tau2_task_success": execution.task_success,
                    "agent_loop": True,
                },
            )
        )
    return executions
