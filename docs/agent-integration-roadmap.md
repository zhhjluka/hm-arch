# HM-Arch Agent Integration Roadmap

## Goal

Make HM-Arch installable and usable as a memory system for Codex, Claude Code,
and Hermes Agent through both Python and npm-based installation workflows.

The roadmap preserves the existing Python memory core and adds stable agent
adapters, automated configuration, cross-agent memory sharing, and a simpler
installation experience over multiple independently releasable versions.

## Product Decisions

- The Python `HMArch` implementation remains the single source of truth for
  memory behavior.
- Codex and Claude Code use lifecycle hooks.
- Hermes Agent uses its native Memory Provider interface.
- Agent integrations call a stable HM-Arch CLI instead of repository-local
  example scripts.
- The npm package is initially an installer and launcher, not a second
  JavaScript implementation of the memory system.
- Configuration changes happen only after an explicit install command. npm
  `postinstall` must not silently modify agent configuration.
- Project-scoped memory is the default. Shared global memory is introduced in a
  later release.
- Each release must remain offline-first and must not require API keys.

## Version Overview

| Version | Goal | User Outcome |
|---------|------|--------------|
| Internal Phase 0 | Prepare stable integration foundations | Shared adapter logic and protocol are ready for product use |
| `v1.1.0` | Python-first three-agent MVP | Install HM-Arch with pip or pipx and connect any supported agent |
| `v1.2.0` | npm installation workflow | Install and manage HM-Arch through npm or npx |
| `v1.3.0` | Cross-agent shared memory | Share durable user memory while preserving project isolation |
| `v1.4.0` | Production reliability and safety | Safer upgrades, concurrency, diagnostics, and sensitive-data handling |
| `v2.0.0` | Python-free npm installation | npm users can install HM-Arch without a preinstalled Python runtime |

---

## Internal Phase 0: Integration Foundations

### Goal

Turn the existing Codex and Claude Code examples into stable integration
building blocks before exposing automated installation commands.

### Scope

1. Define a stable JSON protocol for agent adapters:
   - Recall relevant memory before a turn.
   - Record user and assistant messages after a turn.
   - Run consolidation during idle time or at session boundaries.
   - Return actionable errors without blocking the host agent.

2. Move reusable integration behavior out of `examples/` and into the package:

   ```text
   src/hm_arch/cli/
   src/hm_arch/integrations/common/
   src/hm_arch/integrations/codex/
   src/hm_arch/integrations/claude_code/
   src/hm_arch/integrations/hermes/
   ```

3. Preserve runnable examples as thin wrappers around the packaged
   integrations.

4. Add a unified configuration model for:
   - Database path.
   - Project-scoped or global installation.
   - Recall result count.
   - Maximum injected context size.
   - Consolidation behavior.

5. Update the release policy before registry publication. The current
   documentation states that HM-Arch is distributed only through GitHub
   Releases and must not be published to PyPI or another registry.

### Acceptance Criteria

- Codex and Claude Code adapters reuse the same packaged recall, record, and
  consolidation logic.
- No production adapter depends on paths under `examples/`.
- Existing examples and tests continue to pass.
- The adapter protocol has focused offline tests.
- Release documentation explicitly permits the intended PyPI and npm
  publication workflow before any registry release occurs.

---

## Version 1.1.0: Python-First Three-Agent MVP

### Goal

Allow users to install HM-Arch once with pip or pipx and connect it to Codex,
Claude Code, or Hermes Agent without manually copying scripts or editing JSON.

### Intended User Experience

```bash
pip install hm-arch
# or
pipx install hm-arch

hm-arch install codex
hm-arch install claude-code
hm-arch install hermes

hm-arch status
hm-arch doctor
hm-arch uninstall codex
```

### Scope

#### 1. Stable HM-Arch CLI

Add a packaged command-line entry point with these commands:

```text
hm-arch recall
hm-arch record
hm-arch consolidate
hm-arch install <agent>
hm-arch uninstall <agent>
hm-arch status
hm-arch doctor
```

The CLI becomes the stable executable used by all supported agent
integrations.

#### 2. Codex Installer

- Detect whether Codex is installed.
- Install turn-start recall and turn-end recording hooks.
- Add low-frequency consolidation behavior.
- Enable required Codex hook settings when necessary.
- Support project-level and global installation.
- Merge with existing Codex configuration without deleting user hooks.
- Make repeated installation idempotent.
- Remove only HM-Arch-owned configuration during uninstall.

#### 3. Claude Code Installer

- Detect whether Claude Code is installed.
- Install recall, recording, and consolidation hooks.
- Support project-level and global installation.
- Merge with existing hook arrays and matchers.
- Make repeated installation idempotent.
- Remove only HM-Arch-owned configuration during uninstall.

#### 4. Hermes Agent Memory Provider

Implement a native Hermes Agent Memory Provider that:

- Opens the configured HM-Arch database.
- Recalls relevant memory before each turn.
- Records completed user and assistant turns.
- Saves important information before context compression.
- Consolidates at appropriate idle or session boundaries.
- Closes resources during shutdown.
- Detects an already configured external Memory Provider and refuses to
  silently replace it.

#### 5. PyPI Publication

- Publish the `hm-arch` Python package to PyPI.
- Verify clean `pip install hm-arch` installation.
- Verify clean `pipx install hm-arch` installation.
- Continue publishing wheel and sdist artifacts through GitHub Releases.
- Add registry publication steps to the release checklist.

#### 6. Tests and Documentation

- Add configuration merge tests.
- Add idempotent installation tests.
- Add uninstall preservation tests.
- Add adapter JSON protocol tests.
- Add Hermes Memory Provider lifecycle tests.
- Add manual smoke-test instructions for all three agents.
- Document project-level and global installation commands.

### Out of Scope

- npm installation.
- A Python-free runtime.
- Cross-device synchronization.
- Cloud-hosted memory storage.
- A web-based memory management interface.

### Acceptance Criteria

- A user can install HM-Arch with `pipx install hm-arch`.
- A user can connect any one supported agent within ten minutes.
- Install and uninstall preserve unrelated user configuration.
- Adapter failures do not prevent the host agent from continuing.
- All automated tests pass offline.

---

## Version 1.2.0: npm Installer

### Goal

Provide a familiar installation workflow for Node.js users while continuing to
reuse the Python HM-Arch core.

### Intended User Experience

```bash
npx @hm-arch/installer install codex
npx @hm-arch/installer install claude-code
npx @hm-arch/installer install hermes

npm install -g @hm-arch/installer
hm-arch-install doctor
```

### Scope

1. Create the `@hm-arch/installer` npm package.
2. Detect the operating system, architecture, Node.js version, Python version,
   and installed HM-Arch version.
3. Create an isolated Python virtual environment managed by the npm installer.
4. Install a compatible `hm-arch` Python package version into that environment.
5. Delegate agent configuration to the stable Python CLI.
6. Support install, status, doctor, upgrade, and uninstall commands.
7. Avoid modifying any agent configuration during npm `postinstall`.
8. Add macOS, Linux, and Windows CI coverage.
9. Document how npm and Python package versions are paired.

### Out of Scope

- Reimplementing HM-Arch in TypeScript.
- Shipping standalone native binaries.
- Removing the Python runtime requirement.

### Acceptance Criteria

- A user with Node.js and Python can connect a supported agent with one `npx`
  command.
- The npm installer uses an isolated environment and does not modify the user's
  global Python packages.
- npm uninstall and HM-Arch uninstall preserve unrelated agent configuration.
- Platform installation tests pass on macOS, Linux, and Windows.

---

## Version 1.3.0: Cross-Agent Shared Memory

### Goal

Allow Codex, Claude Code, and Hermes Agent to share durable user memory while
keeping project-specific knowledge isolated.

### Intended User Experience

```bash
hm-arch config set storage.scope project
hm-arch config set storage.global_db ~/.hm-arch/global.db
hm-arch config set storage.project_db .hm-arch/memory.db
```

### Scope

1. Add a two-store model:
   - Global user memory.
   - Project-scoped repository memory.

2. Record memory provenance:
   - Agent name.
   - Project path or project identifier.
   - Session identifier.
   - Creation time.
   - Memory type.

3. Search global and project stores together.
4. Merge, rank, and deduplicate results from both stores.
5. Add filtering by source agent, project, session, and memory type.
6. Prevent project-private content from leaking into unrelated projects.
7. Add memory import, export, and migration commands.
8. Document recommended sharing policies.

### Acceptance Criteria

- A durable user preference recorded by one supported agent can be recalled by
  another supported agent.
- Project-private memory is not returned in unrelated projects.
- Search results expose enough provenance to explain where a memory came from.
- Existing single-project databases remain usable or can be migrated safely.

---

## Version 1.4.0: Production Reliability and Safety

### Goal

Make HM-Arch reliable for long-running use, concurrent access, upgrades, and
real user data.

### Scope

1. Enable and validate SQLite WAL behavior where appropriate.
2. Add lock retries and concurrent multi-agent access tests.
3. Add database schema versioning and automatic migrations.
4. Add sensitive-data filtering for:
   - API keys and tokens.
   - Environment variable values.
   - Private keys.
   - Large tool outputs.
   - Configurable user-defined patterns.

5. Limit injected context size and improve memory deduplication.
6. Clearly mark recalled memory as historical context rather than trusted
   instructions.
7. Add prompt-injection resistance tests for recalled content.
8. Add `hm-arch doctor --fix` for safe, repairable configuration issues.
9. Add structured logs and actionable diagnostics.
10. Maintain an agent compatibility matrix.
11. Add backup, restore, and database repair commands.

### Acceptance Criteria

- Multiple supported agents can use the same configured database without
  routine corruption or unhandled lock failures.
- Schema upgrades preserve existing memories.
- Common secrets are not stored by default.
- Diagnostics identify broken hooks, missing executables, configuration
  conflicts, and database permission problems.
- Backup and restore workflows are documented and tested.

---

## Version 2.0.0: Python-Free npm Installation

### Goal

Allow npm users to install and run HM-Arch without a preinstalled Python
runtime.

### Intended User Experience

```bash
npx @hm-arch/installer install codex
```

The installer downloads and configures the correct HM-Arch executable for the
current platform.

### Scope

1. Package the HM-Arch CLI as standalone executables.
2. Build release artifacts for supported macOS, Linux, and Windows targets.
3. Make the npm package download the correct artifact by platform and
   architecture.
4. Verify downloaded artifacts using checksums and release signatures.
5. Preserve the Python SDK and Python installation workflow.
6. Coordinate npm, PyPI, and GitHub Release versions.
7. Add clean-machine installation tests without Python.

### Acceptance Criteria

- A machine with Node.js but without Python can install HM-Arch through npm.
- The installed executable supports all three agent integrations.
- Downloads are integrity-checked before execution.
- Python SDK users are not required to migrate to npm.

---

## Recommended Execution Order

```text
Internal Phase 0
  -> v1.1.0 Python CLI, three-agent adapters, and PyPI
  -> v1.2.0 npm installer
  -> v1.3.0 cross-agent shared memory
  -> v1.4.0 reliability, migration, safety, and diagnostics
  -> v2.0.0 standalone executable and Python-free npm installation
```

## Release Gates

Before each public release:

- The release-specific automated tests pass.
- The full offline test suite passes.
- A clean install and uninstall smoke test passes.
- Existing user configuration is preserved.
- Documentation matches the shipped commands and configuration format.
- Registry, GitHub Release, and package versions are consistent.
- No release is published without explicit maintainer approval.

