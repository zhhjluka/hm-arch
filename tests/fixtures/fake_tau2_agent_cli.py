#!/usr/bin/env python3
"""Labeled tau2 harness CLI — replays gold actions for offline agent-loop tests."""

from __future__ import annotations

import json
import re
import sys


def _format_functional_action(name: str, arguments: dict[str, object]) -> str:
    parts = [f"{key}={repr(value)}" for key, value in arguments.items()]
    return f"{name}({', '.join(parts)})"


def _tau2_step_response(payload: dict[str, object]) -> dict[str, object]:
    step_index = int(payload.get("step_index", 0))
    gold_actions = list(payload.get("gold_actions") or [])
    if step_index < len(gold_actions):
        action = gold_actions[step_index]
        action_text = _format_functional_action(
            str(action.get("name", "")),
            dict(action.get("arguments") or {}),
        )
    else:
        action_text = "done()"
    return {
        "action": action_text,
        "runner": "fake-tau2-agent-cli",
        "harness_label": "tau2_gold_action_harness",
        "input_tokens": int(payload.get("prompt_token_estimate", 0)),
        "output_tokens": len(re.findall(r"\S+", action_text)),
        "input_token_source": "exact",
        "output_token_source": "exact",
    }


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]

    if len(args) >= 2 and args[0] == "hm-arch-benchmark" and args[1] in {"--help", "-h"}:
        sys.stdout.write("fake tau2 harness CLI\n")
        return 0

    if len(args) >= 2 and args[0] == "hm-arch-benchmark" and args[1] == "tau2-step":
        json_input = ""
        if "--json-input" in args:
            json_input = args[args.index("--json-input") + 1]
        payload = json.loads(json_input)
        sys.stdout.write(json.dumps(_tau2_step_response(payload)))
        return 0

    # Delegate to generic fake agent CLI for capability probes used by CliAgentRunner.open().
    import importlib.util
    from pathlib import Path

    fake_path = Path(__file__).resolve().parent / "fake_agent_cli.py"
    spec = importlib.util.spec_from_file_location("fake_agent_cli", fake_path)
    if spec is None or spec.loader is None:
        sys.stderr.write("fake_agent_cli.py not found\n")
        return 2
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return int(module.main(args))


if __name__ == "__main__":
    raise SystemExit(main())
