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
        context = str(payload.get("context", ""))
        question = str(payload.get("question", ""))
        answer_text = _extract_answer(question, context)
        prompt = f"{context}\n{question}".strip()
        response = {
            "answer": answer_text,
            "input_tokens": _token_count(prompt),
            "output_tokens": _token_count(answer_text),
            "task_success": None,
            "runner": "fake-agent-cli",
        }
        sys.stdout.write(json.dumps(response))
        return 0
    sys.stderr.write("usage: fake-agent hm-arch-benchmark answer --json-input '{...}'\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
