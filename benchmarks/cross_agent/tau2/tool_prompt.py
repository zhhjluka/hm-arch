"""Format tau2 tool schemas for production agent prompts."""

from __future__ import annotations

import json
from typing import Any


def format_tool_signature(tool: Any) -> str:
    """Return a single-line tool signature with argument schema for prompts."""
    schema = getattr(tool, "openai_schema", None)
    if isinstance(schema, dict):
        function = schema.get("function", schema)
        name = str(function.get("name", getattr(tool, "name", tool)))
        parameters = function.get("parameters", {})
        description = str(function.get("description", "")).strip()
        params_json = json.dumps(parameters, separators=(",", ":"), sort_keys=True)
        if description:
            return f"- {name}{params_json}  # {description}"
        return f"- {name}{params_json}"
    return f"- {getattr(tool, 'name', str(tool))}"


def format_tool_signatures(tools: list[Any]) -> str:
    """Return newline-separated tool signatures for agent prompts."""
    return "\n".join(format_tool_signature(tool) for tool in tools)
