# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Version bumps follow [docs/VERSIONING.md](docs/VERSIONING.md). See
[docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) for channel-specific
publication steps and maintainer approval rules.

## [Unreleased]

### Added

- [docs/agents/openclaw.md](docs/agents/openclaw.md) — OpenClaw memory plugin
  install/status/doctor/uninstall, sidecar protocol links, memory modes, and
  provider conflict handling.
- [docs/cross-agent-benchmarks.md](docs/cross-agent-benchmarks.md) — LoCoMo /
  tau2-bench / HotpotQA methodology, five memory modes, agent × backend matrix,
  `real` / `mock-only` / `unavailable` / `unsupported` reporting rules, commands,
  result JSON schema, and LoCoMo pilot artifact references.

### Changed

- README — memory-mode table, cross-agent benchmark entry point, OpenClaw doc link.
- [docs/agents/compatibility-matrix.md](docs/agents/compatibility-matrix.md) —
  OpenClaw row and memory-backend comparison table.
- [docs/npm-installer.md](docs/npm-installer.md), [docs/integration-cli-smoke.md](docs/integration-cli-smoke.md),
  [docs/agents/README.md](docs/agents/README.md), [docs/benchmarks.md](docs/benchmarks.md) —
  synchronized OpenClaw and cross-agent documentation links.

### Pending

- Cross-agent benchmark headline numbers for tau2-bench and HotpotQA (pilot
  artifacts are committed, but full matrix execution and release validation are
  still pending).
- LoCoMo release-note headline numbers (pilot artifact exists; full comparison
  pending provider capacity and larger query counts).

## [2.0.4] - 2026-06-14

### Fixed

- Codex `UserPromptSubmit` recall output now includes
  `hookSpecificOutput.hookEventName`, matching the lifecycle hook schema used by
  Codex and Claude Code.
- Three-agent install, uninstall, status, doctor, and memory smoke paths were
  validated across Hermes, Claude Code, and Codex.

### Changed

- README and agent setup docs now prefer latest stable install commands
  (`pip install hm-arch`, `pipx install hm-arch`, `npm install -g
  @hm-arch/installer`, and `npx @hm-arch/installer ...`) instead of asking users
  to pin a patch version for normal installs.

## [2.0.0] - 2026-06-06

### Added

- Python-free npm verification (MEM-64): clean-machine standalone tests in `packages/installer/test/clean-machine-standalone.test.ts`, version coordination via `scripts/verify_release_versions.py` and `version-coordination.test.ts`, CI `clean-machine-standalone` job, and [docs/v2-migration-guide.md](docs/v2-migration-guide.md)
- Standalone executable tests for Claude Code and Hermes management (`tests/test_standalone_executable.py`)
- PyPI clean-install verification: [docs/pypi-clean-install.md](docs/pypi-clean-install.md) (reproducible `pip` and `pipx` workflows from isolated environments)
- Agent setup guides: [docs/agents/](docs/agents/) (Codex, Claude Code, Hermes — matches shipped `hm-arch` CLI, including Hermes status/doctor-only management)
- Release notes: [docs/RELEASE_NOTES_v2.0.0.md](docs/RELEASE_NOTES_v2.0.0.md) for the coordinated Python, npm, and standalone release
- Packaged Codex and Claude Code hook adapters under `hm_arch.integrations.codex` and `hm_arch.integrations.claude_code`
- Shared `read_hook_payload()` helper in `hm_arch.integrations.common`
- `hm-arch` integration CLI: `install`, `uninstall`, `status`, `doctor` (MEM-47)
- Hermes native Memory Provider under `hm_arch.integrations.hermes` (MEM-46)

### Changed

- Release policy docs: README, [docs/VERSIONING.md](docs/VERSIONING.md), and [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) now describe coordinated v2.0.0+ GitHub, PyPI, npm, and standalone publication with explicit maintainer approval; automated agents still must not publish without instruction
- [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) PyPI section links pip/pipx verification and agent setup guides
- [docs/spec.md](docs/spec.md), [docs/api.md](docs/api.md), and [docs/agent-integration-roadmap.md](docs/agent-integration-roadmap.md) aligned with registry policy (v1.0.0 GitHub-only history vs planned PyPI/npm)
- [docs/agent-integration-roadmap.md](docs/agent-integration-roadmap.md) v1.1.0 UX example no longer implies `hm-arch install hermes`
- README agent integration section documents packaged CLI and links to `docs/agents/`
- `examples/codex_hooks/` and `examples/claude_code_hooks/` are thin wrappers around the packaged adapters (no duplicated memory runtime logic)

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

[Unreleased]: https://github.com/zhhjluka/hm-arch/compare/v2.0.4...HEAD
[2.0.4]: https://github.com/zhhjluka/hm-arch/compare/v2.0.0...v2.0.4
[2.0.0]: https://github.com/zhhjluka/hm-arch/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/zhhjluka/hm-arch/releases/tag/v1.0.0
[0.1.0]: https://github.com/zhhjluka/hm-arch/releases/tag/v0.1.0
