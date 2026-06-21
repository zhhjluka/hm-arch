"""Execute tau2-bench environment scoring helpers.

Gold-action replay in this module is a labeled harness path only. Agent-driven
runs must use :mod:`agent_loop` so tool calls come from the external CLI.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .availability import require_tau2
from .config import Tau2Domain
from .pin import DEFAULT_TASK_SPLIT

GOLD_REPLAY_HARNESS_LABEL = "gold_action_replay_harness"


@dataclass(frozen=True)
class Tau2ToolStep:
    """One real tool invocation against a tau2 domain environment."""

    action_id: str
    tool_name: str
    arguments: dict[str, Any]
    result_preview: str
    duration_ms: float
    error: str | None = None


@dataclass
class Tau2EnvironmentExecution:
    """Outcome of running one tau2 task through the real domain environment."""

    domain: Tau2Domain
    task_id: str
    reward: float | None
    task_success: bool
    action_steps: list[Tau2ToolStep] = field(default_factory=list)
    evaluation: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain.value,
            "task_id": self.task_id,
            "reward": self.reward,
            "task_success": self.task_success,
            "action_steps": [
                {
                    "action_id": step.action_id,
                    "tool_name": step.tool_name,
                    "arguments": step.arguments,
                    "result_preview": step.result_preview,
                    "duration_ms": step.duration_ms,
                    "error": step.error,
                }
                for step in self.action_steps
            ],
            "evaluation": self.evaluation,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


def _build_simulation_from_actions(task, action_steps: list[Tau2ToolStep]):
    """Construct a minimal SimulationRun from executed tool steps."""
    from tau2.data_model.message import AssistantMessage, ToolCall, ToolMessage
    from tau2.data_model.simulation import SimulationRun, TerminationReason
    from tau2.utils.utils import get_now

    messages: list = []
    for index, step in enumerate(action_steps, start=1):
        call_id = f"call_{index}"
        messages.append(
            AssistantMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(id=call_id, name=step.tool_name, arguments=step.arguments)
                ],
            )
        )
        messages.append(
            ToolMessage(
                role="tool",
                id=call_id,
                content=step.result_preview,
                requestor="assistant",
            )
        )
    messages.append(AssistantMessage(role="assistant", content="###STOP###"))
    now = get_now()
    return SimulationRun(
        id=f"hm-arch-env-{task.id}",
        task_id=str(task.id),
        start_time=now,
        end_time=now,
        duration=0.0,
        termination_reason=TerminationReason.AGENT_STOP,
        messages=messages,
    )


def execute_task_environment_gold_replay(
    domain: Tau2Domain,
    task,
    *,
    reset_environment: bool = True,
) -> Tau2EnvironmentExecution:
    """Replay golden evaluation actions — harness-only, not agent-driven."""
    execution = execute_task_environment(domain, task, reset_environment=reset_environment)
    execution.evaluation["harness_label"] = GOLD_REPLAY_HARNESS_LABEL
    return execution


def execute_task_environment(
    domain: Tau2Domain,
    task,
    *,
    reset_environment: bool = True,
) -> Tau2EnvironmentExecution:
    """Run evaluation actions through the real tau2 domain tools and score.

    Prefer :func:`execute_task_environment_gold_replay` in tests to make the
    harness intent explicit. Production comparison runs should call the agent
    loop instead of replaying golden actions here.
    """
    require_tau2()
    from tau2.runner.build import build_environment

    _ = reset_environment  # each call builds a fresh environment instance
    t0 = time.perf_counter()
    execution = Tau2EnvironmentExecution(
        domain=domain,
        task_id=str(task.id),
        reward=None,
        task_success=False,
    )
    try:
        environment = build_environment(domain.value)
        tool_map = {tool.name: tool for tool in environment.get_tools()}
        criteria = task.evaluation_criteria
        actions = list(criteria.actions or []) if criteria else []

        for action in actions:
            step_t0 = time.perf_counter()
            tool = tool_map.get(action.name)
            if tool is None:
                execution.action_steps.append(
                    Tau2ToolStep(
                        action_id=str(action.action_id),
                        tool_name=action.name,
                        arguments=dict(action.arguments or {}),
                        result_preview="",
                        duration_ms=(time.perf_counter() - step_t0) * 1000.0,
                        error=f"unknown tool: {action.name}",
                    )
                )
                continue
            try:
                result = tool(**dict(action.arguments or {}))
                preview = str(result)
                if len(preview) > 500:
                    preview = preview[:497] + "..."
                execution.action_steps.append(
                    Tau2ToolStep(
                        action_id=str(action.action_id),
                        tool_name=action.name,
                        arguments=dict(action.arguments or {}),
                        result_preview=preview,
                        duration_ms=(time.perf_counter() - step_t0) * 1000.0,
                    )
                )
            except Exception as exc:  # noqa: BLE001 — record per-action failure
                execution.action_steps.append(
                    Tau2ToolStep(
                        action_id=str(action.action_id),
                        tool_name=action.name,
                        arguments=dict(action.arguments or {}),
                        result_preview="",
                        duration_ms=(time.perf_counter() - step_t0) * 1000.0,
                        error=str(exc),
                    )
                )

        simulation = _build_simulation_from_actions(task, execution.action_steps)
        from tau2.data_model.simulation import DBCheck, RewardInfo
        from tau2.data_model.tasks import RewardType
        from tau2.evaluator.evaluator_action import ActionEvaluator
        from tau2.environment.toolkit import get_tool_types
        from tau2.runner.build import build_environment as build_env_ctor

        action_reward = ActionEvaluator.calculate_reward(
            task,
            list(simulation.messages or []),
            tool_types=get_tool_types(environment.tools),
        )
        gold_environment = build_env_ctor(domain.value)
        golden_actions = list(task.evaluation_criteria.actions or [])
        for action in golden_actions:
            gold_environment.make_tool_call(
                tool_name=action.name,
                requestor=action.requestor,
                **dict(action.arguments or {}),
            )
        agent_db_match = environment.get_db_hash() == gold_environment.get_db_hash()
        user_db_match = environment.get_user_db_hash() == gold_environment.get_user_db_hash()
        db_reward = 1.0 if agent_db_match and user_db_match else 0.0
        env_reward = RewardInfo(
            reward=db_reward,
            db_check=DBCheck(db_match=bool(db_reward), db_reward=db_reward),
            reward_basis=task.evaluation_criteria.reward_basis,
            reward_breakdown={RewardType.DB: db_reward},
        )
        action_component = float(action_reward.reward or 0.0)
        env_component = float(env_reward.reward or 0.0)
        combined = action_component * env_component
        execution.reward = combined
        execution.task_success = combined >= 1.0
        execution.evaluation = {
            "reward": combined,
            "action_reward": action_component,
            "environment_reward": env_component,
            "action_reward_info": action_reward.model_dump(),
            "environment_reward_info": env_reward.model_dump(),
        }
    except Exception as exc:  # noqa: BLE001 — surface environment failures
        execution.error = str(exc)
    execution.duration_ms = (time.perf_counter() - t0) * 1000.0
    return execution


def execute_domain_tasks(
    domain: Tau2Domain,
    tasks: list,
) -> list[Tau2EnvironmentExecution]:
    """Harness helper: replay golden actions for each task."""
    return [
        execute_task_environment_gold_replay(domain, task, reset_environment=True)
        for task in tasks
    ]
