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
