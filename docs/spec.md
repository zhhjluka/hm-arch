# HM-Arch MVP Development Spec

Source PRD: `/Users/lukaluka/Desktop/AI技术报告/HM-Arch_PRD_开发人员文档.md`

## Goal

Build the first usable version of `hm-arch`, a Python SDK that gives coding agents a human-like memory system with automatic storage, retrieval, decay, and consolidation.

The MVP should make this workflow work reliably:

```python
from hm_arch import HMArch, EventType

memory = HMArch(db_path="./.agent_memory.db")
memory.add("用户偏好 Python", event_type=EventType.CONVERSATION)
results = memory.search("用户喜欢什么语言", top_k=5)
report = memory.consolidate()
```

## MVP Scope

Implement the minimum useful memory loop:

- Public SDK facade: `HMArch`
- Public methods: `add()`, `search()`, `consolidate()`, `get_retention_curve()`, `get_stats()`, `context()`
- Config object and presets: `code_agent`, `chat_agent`, `research_agent`
- Return dataclasses from the PRD
- L0 sensory register, in memory
- L1 working memory, in memory
- L2 episodic buffer, SQLite metadata plus vector index abstraction
- L3 semantic memory, SQLite triples plus vector index abstraction
- Forgetting math: L2 biexponential decay, L3 power-law decay, ASM-2 review scheduling
- Basic consolidation: replay L2 items, extract candidate semantic triples, merge obvious duplicates, update retention, schedule reviews
- Storage layer using SQLite by default
- Vector backend abstraction with a deterministic local fallback for tests
- Examples for basic usage and coding-agent integration
- Pytest coverage for public behavior

## Deferred From MVP

- Full L4 compressed archive implementation
- Full L5 procedural memory
- Full L6 strategy planner
- MCP tool server
- Multi-user or multi-agent sharing
- Encryption and access control
- Distributed storage
- GUI dashboard
- Package registry publishing

The code should leave room for L4-L6, but the MVP must not block on them.

## Key Product Decisions

- `add()` should always succeed without an external LLM key.
- LLM-backed scoring and semantic extraction are optional provider features.
- The default path must use deterministic local fallbacks so tests and demos run offline.
- `add()` writes to L2 synchronously. L3 extraction may happen during `consolidate()`.
- Deletion should be conservative. MVP may mark memories as `deleted` or `deletable`; physical deletion can wait.
- SQLite is the source of truth for memory metadata and content.
- Vector search should be behind an interface so ChromaDB can be swapped or mocked.

## Phase 3 Contract Completion

Phase 3 closes the remaining differences between the offline-first implementation
and the original PRD's externally visible contract.

- Complete `HMArch.forget()`, search filters, per-memory retention prediction,
  and the session context API.
- Integrate L0, L5, and L6 into the public facade and report accurate L0-L6 stats.
- Make automatic consolidation, capacity limits, context-aware forgetting, and
  conservative cleanup operational.
- Implement importance, emotion, repetition, and consistency strength modulation.
- Add optional LLM, embedding, and ChromaDB backends while keeping local fallback
  behavior as the default.
- Validate the PRD's scale and performance targets with reproducible tests.

Release policy:

- HM-Arch is not published to PyPI.
- Versioned releases are published as GitHub Releases.
- Local wheel and sdist builds remain required release verification artifacts.

## Architecture

```text
HMArch
  MemoryCore
    LayerManager
      L0 SensoryRegister
      L1 WorkingMemory
      L2 EpisodicBuffer
      L3 SemanticMemory
    StorageEngine
      SQLiteStore
      VectorStore
    ForgettingController
    ConsolidationEngine
    RetrievalOrchestrator
```

## Public API

The PRD API is authoritative, with one MVP adjustment: provider calls must support local fallback implementations.

Public imports:

```python
from hm_arch import (
    HMArch,
    MemoryConfig,
    EventType,
    MemoryReceipt,
    SearchResult,
    MemoryItem,
    ConsolidationReport,
    RetentionCurve,
    MemoryStats,
)
```

## Storage

Create SQLite tables:

- `memory_index`
- `episodes`
- `semantics`
- `skills`
- `meta_memory`
- `review_queue`
- `consolidation_log`

For MVP, `skills` and `meta_memory` can exist before their full behavior is implemented.

## Testing Strategy

Tests should focus on public behavior:

- Config presets are stable and reject unknown presets.
- Storage initializes all tables.
- `add()` returns a `MemoryReceipt` and persists an L2 episode.
- `search()` returns relevant results with layer, retention, relevance, and score.
- L2 and L3 decay formulas match expected PRD values.
- Consolidation creates semantic memories from episodic inputs when extractor fallback detects clear facts.
- Contradictory semantic facts mark older rows as superseded.
- Reopening the same database preserves searchable memories.

## Cursor/Codex Working Rules

- Cursor should work one Linear issue at a time.
- Each issue must include scope, acceptance criteria, and out-of-scope notes.
- Codex reviews issue outputs, runs tests, fixes integration gaps, and updates task status.
- If Cursor hits ambiguity, it should leave a comment instead of inventing product behavior.
- Avoid large unrelated refactors.
