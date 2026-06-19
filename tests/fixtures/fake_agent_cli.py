#!/usr/bin/env python3
"""Fake agent CLI for offline cross-agent benchmark smoke tests."""

from __future__ import annotations

import json
import re
import sys


def _extract_answer(question: str, context: str) -> str:
    q = question.lower()
    ctx = context.lower()
    if "language" in q and "python" in ctx:
        return "Python"
    if "project context" in q and "hm-arch" in ctx:
        return "hm-arch offline benchmarks with isolated agent homes"
    if "cat" in q and "pixel" in ctx:
        return "Pixel"
    if "city" in q and "seattle" in ctx:
        return "Seattle"
    match = re.search(r"prefers ([A-Za-z]+)", context, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    if context.strip():
        return context.strip().splitlines()[-1].lstrip("- ").strip()
    return "unknown"


def _token_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _parse_prompt_from_payload(payload: dict[str, str]) -> tuple[str, str]:
    context = str(payload.get("context", ""))
    question = str(payload.get("question", ""))
    return context, question


def _benchmark_answer_response(context: str, question: str) -> dict[str, object]:
    answer_text = _extract_answer(question, context)
    prompt = f"{context}\n{question}".strip()
    return {
        "answer": answer_text,
        "input_tokens": _token_count(prompt),
        "output_tokens": _token_count(answer_text),
        "task_success": None,
        "runner": "fake-agent-cli",
        "input_token_source": "exact",
        "output_token_source": "exact",
    }


def _emit_codex_jsonl(context: str, question: str) -> int:
    answer_text = _extract_answer(question, context)
    events = [
        {"type": "thread.started", "thread_id": "fake-thread"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {"id": "item_1", "type": "agent_message", "text": answer_text},
        },
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": _token_count(f"{context}\n{question}"),
                "cached_input_tokens": 0,
                "output_tokens": _token_count(answer_text),
                "reasoning_output_tokens": 0,
            },
        },
    ]
    for event in events:
        sys.stdout.write(json.dumps(event) + "\n")
    return 0


def _split_prompt(prompt: str) -> tuple[str, str]:
    marker = "\n\nQuestion: "
    if marker in prompt:
        context, question = prompt.split(marker, 1)
        return context, question
    return "", prompt


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]

    if len(args) >= 2 and args[0] == "hm-arch-benchmark" and args[1] in {"--help", "-h"}:
        sys.stdout.write("fake benchmark CLI\n")
        return 0

    if len(args) >= 2 and args[0] == "hm-arch-benchmark" and args[1] == "answer":
        json_input = ""
        if "--json-input" in args:
            json_input = args[args.index("--json-input") + 1]
        payload = json.loads(json_input)
        context, question = _parse_prompt_from_payload(payload)
        sys.stdout.write(json.dumps(_benchmark_answer_response(context, question)))
        return 0

    if args and args[0] == "exec" and "--json" in args:
        prompt = args[-1]
        context, question = _split_prompt(prompt)
        return _emit_codex_jsonl(context, question)

    if args and args[0] == "exec" and args[-1] == "--help":
        sys.stdout.write("fake codex exec\n")
        return 0

    if "-p" in args and "--output-format" in args:
        prompt = args[args.index("-p") + 1]
        context, question = _split_prompt(prompt)
        answer_text = _extract_answer(question, context)
        sys.stdout.write(
            json.dumps(
                {
                    "result": answer_text,
                    "usage": {
                        "input_tokens": _token_count(f"{context}\n{question}"),
                        "output_tokens": _token_count(answer_text),
                    },
                }
            )
        )
        return 0

    if args == ["--help"]:
        sys.stdout.write(
            "Usage: fake-agent [-z PROMPT] [--output-format json] "
            "[hm-arch-benchmark ...]\n-z  one-shot\n"
        )
        return 0

    if args and args[0] == "-z":
        prompt = args[1] if len(args) > 1 else ""
        context, question = _split_prompt(prompt)
        sys.stdout.write(_extract_answer(question, context))
        return 0

    if len(args) >= 2 and args[0] == "agent" and "--message" in args:
        prompt = args[args.index("--message") + 1]
        context, question = _split_prompt(prompt)
        answer_text = _extract_answer(question, context)
        sys.stdout.write(
            json.dumps(
                {
                    "reply": answer_text,
                    "usage": {
                        "inputTokens": _token_count(f"{context}\n{question}"),
                        "outputTokens": _token_count(answer_text),
                    },
                }
            )
        )
        return 0

    if len(args) >= 2 and args[0] == "agent" and args[1] == "--help":
        sys.stdout.write("fake openclaw agent --message\n")
        return 0

    sys.stderr.write(
        "usage: fake-agent hm-arch-benchmark answer | exec --json PROMPT | "
        "-z PROMPT | agent --message PROMPT\n"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
