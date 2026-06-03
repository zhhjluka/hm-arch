#!/usr/bin/env python3
"""Regenerate docs/api.md from the installed hm_arch package.

Run from the repository root after editable install::

    python -m pip install -e .
    python scripts/generate_api_docs.py

The generator introspects public exports and dataclass fields so the API
reference stays aligned with the code.
"""

from __future__ import annotations

import dataclasses
import enum
import inspect
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / "docs" / "api.md"


def _field_table(cls: type) -> list[str]:
    lines: list[str] = []
    if not dataclasses.is_dataclass(cls):
        return lines
    lines.append("| Field | Type | Description |")
    lines.append("|-------|------|-------------|")
    for f in dataclasses.fields(cls):
        doc = (f.metadata.get("doc") or "").strip()
        if not doc and cls.__doc__:
            # fall back: no per-field docs in dataclass metadata
            doc = ""
        type_name = (
            inspect.formatannotation(f.type)
            if f.type is not dataclasses.MISSING
            else "Any"
        )
        default = ""
        if f.default is not dataclasses.MISSING and f.default is not None:
            default = f" (default: `{f.default!r}`)" if f.default != dataclasses.MISSING else ""
        elif f.default_factory is not dataclasses.MISSING:  # type: ignore[comparison-overlap]
            default = " (factory)"
        lines.append(f"| `{f.name}` | `{type_name}` |{default}|")
    return lines


def _enum_members(enum_cls: type[enum.Enum]) -> list[str]:
    lines = ["| Member | Value |", "|--------|-------|"]
    for member in enum_cls:
        lines.append(f"| `{member.name}` | `{member.value}` |")
    return lines


def _method_section(obj: Any, heading: str) -> list[str]:
    lines = [f"### `{heading}`", ""]
    doc = inspect.getdoc(obj) or "_No docstring._"
    lines.append(doc)
    lines.append("")
    sig = str(inspect.signature(obj))
    lines.append(f"```python\n{heading}{sig}\n```")
    lines.append("")
    return lines


def build_markdown() -> str:
    import hm_arch
    from hm_arch import (
        ConsolidationReport,
        EventType,
        ForgetResult,
        HMArch,
        MemoryConfig,
        MemoryItem,
        MemoryReceipt,
        MemoryStats,
        RetentionCurve,
        SearchResult,
    )
    from hm_arch import layers as layers_pkg

    version = hm_arch.__version__
    lines: list[str] = [
        "# HM-Arch API reference",
        "",
        f"_Generated from `hm_arch` v{version}. Regenerate with "
        f"`python scripts/generate_api_docs.py`._",
        "",
        "Stable integrations should import from the top-level package:",
        "",
        "```python",
        "from hm_arch import HMArch, MemoryConfig, EventType",
        "```",
        "",
        "Layer implementations (`hm_arch.layers`) are available for advanced",
        "use but are not required for the primary agent workflow.",
        "",
        "---",
        "",
        "## Package exports (`hm_arch`)",
        "",
        "| Name | Kind |",
        "|------|------|",
    ]
    export_kinds = {
        "__version__": "str",
        "HMArch": "class",
        "MemoryConfig": "dataclass",
        "EventType": "enum",
        "MemoryReceipt": "dataclass",
        "MemoryItem": "dataclass",
        "SearchResult": "dataclass",
        "ConsolidationReport": "dataclass",
        "RetentionCurve": "dataclass",
        "MemoryStats": "dataclass",
        "ForgetResult": "dataclass",
    }
    for name in hm_arch.__all__:
        lines.append(f"| `{name}` | {export_kinds.get(name, 'export')} |")

    lines += ["", "---", "", "## `HMArch`", ""]
    for method_name in (
        "__init__",
        "add",
        "search",
        "forget",
        "consolidate",
        "get_retention_curve",
        "get_stats",
        "agent_context",
        "context",
        "close",
        "__enter__",
        "__exit__",
    ):
        method = getattr(HMArch, method_name, None)
        if method is None:
            continue
        heading = f"HMArch.{method_name}" if method_name != "__init__" else "HMArch(...)"
        if method_name == "__init__":
            lines += _method_section(method, "HMArch.__init__")
        else:
            lines += _method_section(method, f"HMArch.{method_name}")

    lines += ["---", "", "## `MemoryConfig`", ""]
    lines.append(inspect.getdoc(MemoryConfig) or "")
    lines.append("")
    lines += _field_table(MemoryConfig)
    lines += [
        "",
        "### Presets",
        "",
        "`MemoryConfig.preset(name)` — `name` is one of:",
        "",
        "- `code_agent`",
        "- `chat_agent`",
        "- `research_agent`",
        "",
    ]

    lines += ["---", "", "## `EventType`", ""]
    lines += _enum_members(EventType)
    lines.append("")

    dataclasses_doc = [
        ("MemoryReceipt", MemoryReceipt, "Returned by `HMArch.add()`."),
        ("MemoryItem", MemoryItem, "Single hit inside `SearchResult.results`."),
        ("SearchResult", SearchResult, "Returned by `HMArch.search()`."),
        ("ConsolidationReport", ConsolidationReport, "Returned by `HMArch.consolidate()`."),
        ("RetentionCurve", RetentionCurve, "Returned by `HMArch.get_retention_curve()`."),
        ("MemoryStats", MemoryStats, "Returned by `HMArch.get_stats()`."),
        ("ForgetResult", ForgetResult, "Type for future `forget()` API; exported for contract stability."),
    ]
    for title, cls, note in dataclasses_doc:
        lines += ["---", "", f"## `{title}`", "", note, ""]
        lines.append(inspect.getdoc(cls) or "")
        lines.append("")
        lines += _field_table(cls)
        lines.append("")

    lines += [
        "---",
        "",
        "## Memory layers (`hm_arch.layers`)",
        "",
        "Advanced layer APIs (offline tests cover these modules):",
        "",
        "| Class | Role |",
        "|-------|------|",
        "| `L0SensoryRegister` | Bounded sensory window |",
        "| `L1WorkingMemory` | Session working memory |",
        "| `L2EpisodicBuffer` | Durable episodic buffer (SQLite) |",
        "| `L3SemanticMemory` | Semantic triple store |",
        "| `L4EpisodicLTM` | Gzip episodic archive |",
        "| `L5ProceduralMemory` | Procedural skills |",
        "| `L6MetaMemory` | Usage tracking and meta policies |",
        "",
        "Supporting types: `LayerItem`, `EpisodicItem`, `SemanticFact`,",
        "`ArchivedEpisodic`, `SkillRecord`, `HotMemoryRecord`, `StrategyPlan`.",
        "",
        f"Full export list: `{', '.join(layers_pkg.__all__)}`.",
        "",
    ]

    return "\n".join(lines) + "\n"


def main() -> int:
    # Ensure src layout is importable when run without install
    src = REPO_ROOT / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    markdown = build_markdown()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(markdown, encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)} ({len(markdown)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
