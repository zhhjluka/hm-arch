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
    from hm_arch.forgetting import (
        ContextAwareScore,
        ForgettingController,
        ManualTimeProvider,
        PRD_STRENGTH_MAX,
        STRENGTH_BASE,
        SystemTimeProvider,
        TimeProvider,
        compute_initial_strength,
        importance_modifier_factor,
    )

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
        "Advanced lifecycle helpers live in ``hm_arch.forgetting``:",
        "",
        "```python",
        "from hm_arch.forgetting import ManualTimeProvider, ForgettingController",
        "from hm_arch.forgetting import compute_initial_strength, strength_bounds",
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
        "run_lifecycle",
        "get_retention_curve",
        "get_stats",
        "store_skill",
        "match_skill",
        "list_skills",
        "record_skill_result",
        "get_skill",
        "set_policy",
        "get_policy",
        "get_hot_memories",
        "strategy_plan",
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
        "---",
        "",
        "## Optional providers and vector backends (HM-30)",
        "",
        "HM-Arch is **offline-first**. Local token-overlap search and pattern-based",
        "semantic extraction are the defaults. Remote LLM, embedding, and ChromaDB",
        "backends are opt-in and never required for tests or demos.",
        "",
        "### Opt-in switch",
        "",
        "| Setting | Default | Effect |",
        "|---------|---------|--------|",
        "| `enable_llm_providers` | `False` | When `False`, all provider fields are ignored; "
        "local heuristics and `vector_backend='local'` are used. |",
        "| `provider_fallback_to_local` | `True` | When `True`, missing API keys, missing "
        "optional packages, and **runtime** provider HTTP/parsing failures fall back to "
        "local implementations. When `False`, those conditions raise actionable errors. |",
        "",
        "### LLM providers (`llm_provider`)",
        "",
        "| Value | Chat API | Default model when `llm_model` is unset |",
        "|-------|----------|----------------------------------------|",
        "| `local` | None (heuristic importance + pattern triples) | — |",
        "| `openai` | OpenAI-compatible `/chat/completions` | `gpt-4o-mini` |",
        "| `deepseek` | DeepSeek `/chat/completions` | `deepseek-chat` |",
        "",
        "Set `llm_api_key` or `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` (also `HM_ARCH_*` variants).",
        "Optional `llm_base_url` overrides the provider host.",
        "",
        "Provider-backed importance scoring runs in `HMArch.add()` when "
        "`enable_llm_providers=True`. Provider-backed semantic extraction runs in "
        "`HMArch.consolidate()` via `ProviderSemanticExtractor`.",
        "",
        "### Embedding providers (`embedding_provider`)",
        "",
        "| Value | Supported | Notes |",
        "|-------|-----------|-------|",
        "| `local` | Yes | Deterministic hash embeddings (default). |",
        "| `openai` | Yes | `/embeddings`; default model `text-embedding-3-small` when unset. |",
        "| `deepseek` | **No** | DeepSeek's public API does not document embeddings. "
        "With fallback enabled, local embeddings are used; otherwise configuration raises. |",
        "",
        "`embedding_dim` is enforced for OpenAI embeddings: v3 models send a `dimensions` "
        "request field; every returned vector must match `embedding_dim` or the provider "
        "falls back locally / raises `ProviderRuntimeError` per `provider_fallback_to_local`.",
        "",
        "### Vector backends (`vector_backend`)",
        "",
        "| Value | Dependency | Persistence |",
        "|-------|------------|---------------|",
        "| `local` | stdlib only | In-process token overlap (default). |",
        "| `chroma` | `pip install 'hm-arch[chroma]'` | `chroma_persist_directory` or "
        "`{db_parent}/chroma`; collections `{chroma_collection_prefix}_l2_episodic` and "
        "`{prefix}_l3_semantic`. SQLite remains the source of truth; L2/L3 rebuild vector "
        "indexes from SQLite on startup. |",
        "",
        "### Protocols (`hm_arch.providers`)",
        "",
        "Advanced integrations may use:",
        "",
        "- `LLMProviderProtocol` — `score_importance`, `extract_semantic_triples`",
        "- `EmbeddingProviderProtocol` — `embed`",
        "- `resolve_llm_provider`, `resolve_embedding_provider`, `create_vector_store`",
        "",
        "Failures with fallback disabled raise `ProviderRuntimeError` or "
        "`ProviderConfigurationError`.",
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
        ("ForgetResult", ForgetResult, "Returned by `HMArch.forget()`."),
        ("ContextAwareScore", ContextAwareScore, "PRD forgetting score decomposition."),
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
        "## Forgetting lifecycle (`hm_arch.forgetting`)",
        "",
        "| Name | Kind |",
        "|------|------|",
        f"| `TimeProvider` | protocol |",
        f"| `SystemTimeProvider` | class |",
        f"| `ManualTimeProvider` | class |",
        f"| `ForgettingController` | class |",
        f"| `ContextAwareScore` | dataclass |",
        "",
        inspect.getdoc(ForgettingController) or "",
        "",
        "### `TimeProvider`",
        "",
        inspect.getdoc(TimeProvider) or "",
        "",
        f"```python\nclass TimeProvider:\n    def now(self) -> datetime: ...\n```",
        "",
        "### `ManualTimeProvider`",
        "",
        inspect.getdoc(ManualTimeProvider) or "",
        "",
        "### PRD forgetting score",
        "",
        "The context-aware forgetting score is:",
        "",
        "```",
        "Forgetting_Score =",
        "    0.35 * (1 - R)",
        "  + 0.25 * (1 - Relevance)",
        "  + 0.15 * Redundancy",
        "  + 0.15 * Contradiction",
        "  + 0.10 * Privacy",
        "```",
        "",
        "`HMArch.forget(memory_id=None)` applies this score during the global scan.",
        "Automated physical cleanup waits for `deletion_safety_period_hours`.",
        "",
        "### Memory strength modulation (HM-29)",
        "",
        "PRD multiplicative initial strength (offline, deterministic):",
        "",
        "```",
        "S = S_base * I_mod * E_mod * R_mod * C_mod",
        "```",
        "",
        f"* ``S_base = {STRENGTH_BASE}``",
        "* ``I_mod`` in ``[1.0, 2.0]`` from importance ``[0, 1]``",
        "* ``E_mod`` in ``[0.8, 1.5]`` from emotion ``[0, 1]``",
        "* ``R_mod`` in ``[1.0, 3.0]``: ``1.0 + 0.3 * (encode_repetitions + successful_retrievals)``",
        "* ``C_mod`` in ``[0.5, 1.5]`` (neutral ``1.0``, consistent ``1.5``, superseded conflict ``0.5``)",
        "",
        f"Maximum product (before clamp): ``{PRD_STRENGTH_MAX}``. "
        "``MemoryConfig.strength_min``, ``strength_max``, "
        "``retrieval_reinforcement_increment``, and ``retrieval_relevance_threshold`` "
        "control bounds and retrieval reinforcement.",
        "",
        "Retention scales as ``R(t) = min(1.0, R_layer(t) * S)``. "
        "At encode, ``current_retention = min(1.0, S)`` while ``initial_strength`` keeps the full PRD "
        "multiplier. Each successful search reinforces each underlying L2/L3 memory at most once "
        "(best relevance wins when L0/L1 and L2 share a link). "
        "Each successful retrieval increments ``successful_retrievals`` and recomputes ``S``.",
        "",
        "Exported helpers include ``compute_initial_strength``, "
        "``apply_retrieval_reinforcement``, ``StrengthFactors``, and modifier factor functions.",
        "",
    ]

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
