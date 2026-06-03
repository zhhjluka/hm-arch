# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Version bumps follow [docs/VERSIONING.md](docs/VERSIONING.md). Releases are
published through GitHub Releases only; HM-Arch is not published to PyPI.

## [Unreleased]

## [1.0.0] - 2026-06-03

Phase 3 stable release: complete public PRD contract, seven-layer facade integration,
automatic lifecycle management, optional provider backends, and reproducible PRD
benchmarks. Distributed via GitHub Releases (wheel and sdist artifacts); not on PyPI.

### Added

- `HMArch.forget()` with `ForgetResult` and searchable-layer cleanup
- `agent_context()` and PRD session `context()` API (`load_session` / `save_session`)
- L0, L5, and L6 integrated into the facade with accurate L0–L6 stats
- Automatic consolidation scheduling, capacity limits, context-aware forgetting, and conservative physical cleanup
- Importance, emotion, repetition, and consistency strength modulation (`hm_arch.forgetting.strength`)
- PRD scale and performance benchmarks (`benchmarks/`, `tests/prd_benchmarks/`, `scripts/run_prd_benchmarks.py`, `docs/benchmarks.md`); strict PRD comparisons (`<` / `>`), Week 9 report-only, uniform 30d vs mixed-age L4 scenarios with documented PRD formula deviation; excluded from default `pytest` via the `benchmark` marker
- Optional LLM provider protocol with DeepSeek and OpenAI implementations (stdlib HTTP; mocked in tests)
- Optional embedding providers and `ChromaVectorStore` behind `VectorStoreProtocol`
- `MemoryConfig.enable_llm_providers`, `vector_backend`, and Chroma persistence settings with local fallback defaults
- Prepared GitHub Release notes: [docs/RELEASE_NOTES_v1.0.0.md](docs/RELEASE_NOTES_v1.0.0.md)

### Changed

- Public API defaults and search filters aligned with the supported PRD contract (`docs/spec.md`)
- Release checklist documents clean wheel/sdist verification in isolated environments

## [0.1.0] - 2026-06-02

Phase 2 release-ready SDK: L4–L6 layers, full sleep consolidation, agent hook examples,
30-day simulation tests, and release documentation.

### Added

- `HMArch` facade: `add`, `search`, `consolidate`, `get_retention_curve`, `get_stats`, `context`, `close`
- Public types: `EventType`, `MemoryReceipt`, `MemoryItem`, `SearchResult`, `ConsolidationReport`, `RetentionCurve`, `MemoryStats`, `ForgetResult`
- `MemoryConfig` with `code_agent`, `chat_agent`, and `research_agent` presets
- Memory layers L0–L6 (`hm_arch.layers`) and offline SQLite + vector fallback storage
- Agent hook examples for Codex and Claude Code
- `examples/release_smoke.py` and `docs/api.md` API reference
- `docs/RELEASE_CHECKLIST.md`, `docs/VERSIONING.md`, and `scripts/generate_api_docs.py`

[Unreleased]: https://github.com/ZhangHangjianMA/memashuman/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/ZhangHangjianMA/memashuman/releases/tag/v1.0.0
[0.1.0]: https://github.com/ZhangHangjianMA/memashuman/releases/tag/v0.1.0
