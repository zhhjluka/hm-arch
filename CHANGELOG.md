# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Version bumps follow [docs/VERSIONING.md](docs/VERSIONING.md). PyPI publishing is
manual and requires explicit maintainer approval (see [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md)).

## [Unreleased]

### Added

- (none)

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

[Unreleased]: https://github.com/hm-arch/hm-arch/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/hm-arch/hm-arch/releases/tag/v0.1.0
