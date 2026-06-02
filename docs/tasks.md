# HM-Arch Task Breakdown

This file mirrors the initial Linear queue. Linear is the task dispatcher; this file is the repository-local source of context.

## M0: Project Scaffold

### HM-1: Scaffold Python package

Scope:
- Create `pyproject.toml`
- Create `src/hm_arch/`
- Export public SDK names from `src/hm_arch/__init__.py`
- Add `tests/` and `examples/`

Acceptance:
- `python -m pip install -e .` succeeds
- `python -c "import hm_arch"` succeeds
- `pytest` discovers the test suite

Out of scope:
- No storage behavior
- No memory layers

### HM-2: Implement public types and config

Scope:
- Implement `src/hm_arch/types.py`
- Implement `src/hm_arch/config.py`
- Include `EventType`
- Include `MemoryConfig.preset("code_agent" | "chat_agent" | "research_agent")`

Acceptance:
- All PRD dataclasses are importable
- Presets return distinct values
- Unknown preset raises `ValueError`

Out of scope:
- No LLM provider
- No storage

## M1: Storage Foundation

### HM-3: Implement SQLite storage

Scope:
- Create `src/hm_arch/storage/sqlite.py`
- Initialize PRD tables
- Provide simple execute/query helpers
- Use ISO 8601 timestamps and JSON text fields

Acceptance:
- Temporary DB initializes all expected tables
- Reopening the DB preserves data
- Tests do not share state

Out of scope:
- No ChromaDB dependency required

### HM-4: Implement vector store abstraction with local fallback

Scope:
- Create `src/hm_arch/storage/vector.py`
- Define a small vector store protocol
- Implement deterministic local vector fallback for tests
- Keep ChromaDB integration optional

Acceptance:
- Upsert/query/delete work in tests
- Query returns stable relevance ordering
- No external API key required

Out of scope:
- No production vector tuning

## M2: Add/Search MVP

### HM-5: Implement L0 and L1 memory layers

Scope:
- Implement `layers/base.py`
- Implement `layers/l0_sensory.py`
- Implement `layers/l1_working.py`

Acceptance:
- L0 keeps a bounded recent window
- L1 keeps bounded session items
- Overflow evicts oldest entries

Out of scope:
- No persistence

### HM-6: Implement L2 episodic buffer

Scope:
- Implement `layers/l2_episodic.py`
- Encode events into SQLite `episodes` and `memory_index`
- Upsert event text into vector store
- Retrieve candidates with retention metadata

Acceptance:
- `encode()` persists an episode
- `retrieve()` finds recently added relevant content
- Restarting the DB preserves L2 content

Out of scope:
- No L3 semantic extraction

### HM-7: Implement L3 semantic memory

Scope:
- Implement `layers/l3_semantic.py`
- Upsert semantic triples
- Search semantic triples
- Detect same entity/relation conflicting values
- Mark older facts as `superseded`

Acceptance:
- `upsert("user", "likes", "Python")` is searchable
- Conflicting value marks older memory as superseded
- Latest active value ranks first

Out of scope:
- No LLM extraction

### HM-8: Implement HMArch facade add/search

Scope:
- Implement `core.py`
- Implement `HMArch.add()`
- Implement `HMArch.search()`
- Combine L1, L3, and L2 search
- Score by `retention * relevance * layer_priority`

Acceptance:
- Basic usage example runs
- Search result includes source layer and score
- Results are sorted descending by score

Out of scope:
- No full consolidation cycle

## M3: Forgetting and Consolidation

### HM-9: Implement forgetting math

Scope:
- Implement `forgetting/decay.py`
- Implement `forgetting/asm2.py`
- Implement retention curve prediction

Acceptance:
- L2 30-day retention is approximately `0.26`
- L3 30-day retention is approximately `0.63`
- ASM-2 examples from PRD pass

Out of scope:
- No database batch updates

### HM-10: Implement basic consolidation

Scope:
- Implement `consolidation/replay.py`
- Implement fallback semantic extractor
- Implement `ConsolidationEngine.run_consolidation_cycle()`
- Update retention fields
- Schedule reviews for important low-retention memories

Acceptance:
- Clear preference text creates a semantic triple
- Consolidation returns `ConsolidationReport`
- Review queue is populated for important stale memories

Out of scope:
- No heavy LLM pipeline
- No physical deletion

## M4: Developer Experience

### HM-11: Implement stats, context manager, and examples

Scope:
- Implement `HMArch.get_stats()`
- Implement `HMArch.context()`
- Add `examples/basic_usage.py`
- Add `examples/agent_integration.py`

Acceptance:
- Stats report by-layer counts and storage size
- Context manager saves/restores session state
- Examples run offline

Out of scope:
- No Codex or Claude hook automation yet

### HM-12: Integration pass and docs

Scope:
- Tighten README
- Add testing instructions
- Run full test suite
- Fix integration gaps across earlier issues

Acceptance:
- Fresh clone setup works from README
- `pytest` passes
- MVP demo runs end to end

Out of scope:
- No PyPI publish

---

# Phase 2 Task Breakdown

Phase 2 completes the seven-layer architecture and prepares the SDK for real
agent integration and release.

## M5: L4 Episodic Long-Term Archive

### HM-18: Implement L4 episodic long-term archive

Scope:
- Create `src/hm_arch/layers/l4_ltm.py`
- Store archived episodic memories as `ltm/YYYY-MM/{hash}.json.gz`
- Preserve original `memory_id`, content, layer, timestamps, retention, importance, and metadata
- Provide `archive()`, `retrieve()`, `list_archives()`, and `purge()` APIs
- Add tests for gzip round-trip, month partitioning, metadata preservation, and purge behavior

Acceptance:
- A low-retention L2 memory can be archived to a deterministic `.json.gz` path
- Archived payload can be retrieved by `memory_id`
- Archive files are valid JSON after gzip decompression
- `purge()` removes an archive file and returns a structured result
- Tests use `tmp_path` and do not share state

Out of scope:
- No search integration yet
- No consolidation integration yet

### HM-19: Wire L4 into search and consolidation

Scope:
- Integrate L4 with `HMArch.search()`
- Integrate L4 archive movement into consolidation
- Apply L4 layer priority `0.5`
- Mark archived memories in SQLite `memory_index`
- Ensure archived L2 memories remain discoverable through search

Acceptance:
- `memory.consolidate()` archives eligible L2 memories below `l2_archive_threshold`
- `memory.search()` can return L4 results with `layer=4`
- L4 results rank below stronger L1/L2/L3 results when relevance is similar
- Archived memory metadata includes source L2 memory ID
- Full test suite passes

Out of scope:
- No physical deletion automation beyond explicit purge

## M6: L5 Procedural Memory

### HM-20: Implement L5 procedural memory

Scope:
- Create `src/hm_arch/layers/l5_procedural.py`
- Implement `store_skill()`, `match_skill()`, `list_skills()`, and `record_skill_result()`
- Use SQLite `skills` table
- Track `usage_count`, `success_rate`, `last_used_at`, and `average_duration_ms`
- Add tests for skill creation, update, matching, and stats

Acceptance:
- `store_skill("git_push", ...)` persists a skill
- `match_skill("推代码")` returns the most relevant skill
- Reusing a skill increments `usage_count`
- Recording success/failure updates `success_rate`
- Reopening the DB preserves skills

Out of scope:
- No executable sandbox for skill code
- No automatic skill extraction from conversations

## M7: L6 Meta Memory

### HM-21: Implement L6 meta memory

Scope:
- Create `src/hm_arch/layers/l6_meta.py`
- Implement `track_access()`, `get_hot_memories()`, `strategy_plan()`, and `set_policy()`
- Use SQLite `meta_memory` plus `memory_index.access_count` / `last_accessed_at`
- Track access counts by memory ID and layer
- Expose simple policy values for retrieval/consolidation tuning

Acceptance:
- Every successful search can record access events
- `get_hot_memories()` returns most accessed memories in descending order
- `strategy_plan()` returns current policy values and simple recommendations
- Policies persist across process restarts
- Tests cover access tracking and policy persistence

Out of scope:
- No RL-based strategy learning
- No multi-agent shared meta memory

## M8: Full Sleep Consolidation

### HM-22: Full sleep consolidation cycle

Scope:
- Upgrade `ConsolidationEngine` to run the full PRD sleep cycle
- Replay weighted L2 samples
- Extract L3 semantic triples
- Merge redundant semantics
- Resolve conflicting semantics by superseding old facts
- Update L2/L3 retention
- Archive eligible L2 memories to L4
- Schedule reviews for important low-retention memories
- Record a complete `consolidation_log` row

Acceptance:
- `memory.consolidate()` returns accurate `ConsolidationReport` counts
- Redundant semantic facts merge when similarity exceeds threshold
- Conflicting facts preserve version history through `superseded_by`
- L2 memories below archive threshold move to L4
- Review queue receives important stale memories
- A 7-day simulated agent scenario passes

Out of scope:
- No mandatory external LLM dependency
- No background daemon yet

## M9: Agent Hooks

### HM-23: Codex and Claude Code hook examples

Scope:
- Add `examples/codex_hooks/`
- Add `examples/claude_code_hooks/`
- Provide turn-start memory context injection examples
- Provide turn-end conversation recording examples
- Provide idle consolidation examples
- Add README section for hook integration

Acceptance:
- Hook examples are importable and runnable offline
- Turn-start hook returns memory context text for a task
- Turn-end hook records user/agent messages
- Idle hook triggers consolidation without crashing
- Examples avoid hardcoded user-specific paths

Out of scope:
- No MCP server implementation
- No automatic installation into Codex or Claude Code config

## M10: Long-Run Simulation and Release

### HM-24: End-to-end 30-day simulation tests

Scope:
- Add `tests/test_simulation_30_day.py`
- Simulate 30 days of coding-agent memory events
- Verify L2/L3 retention behavior
- Verify preference changes supersede old semantics
- Verify L4 archive growth and review queue behavior

Acceptance:
- L2 30-day retention is approximately `0.26`
- L3 30-day retention is approximately `0.63`
- User preference change returns latest semantic fact first
- L4 receives eligible archived memories
- Test runtime stays reasonable for CI/local use

Out of scope:
- No large benchmark dataset
- No real LLM calls

### HM-25: Release readiness and PyPI prep

Scope:
- Finalize package metadata in `pyproject.toml`
- Add changelog and release checklist
- Add API docs generation command or static API reference
- Verify README quickstart from a fresh environment
- Add `examples/release_smoke.py` if useful
- Prepare version bump strategy

Acceptance:
- Fresh clone setup works
- `python -m pip install -e ".[dev]" && pytest` passes
- `python examples/basic_usage.py` passes
- Public API docs list all supported methods and dataclasses
- Release checklist clearly distinguishes test, build, tag, and publish steps

Out of scope:
- Do not publish to PyPI without explicit user approval
