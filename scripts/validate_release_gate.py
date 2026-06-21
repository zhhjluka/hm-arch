#!/usr/bin/env python3
"""MEM-79 release gate: validate versions, docs, and benchmark artifact claims."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION_PY = REPO_ROOT / "src" / "hm_arch" / "_version.py"
INSTALLER_JSON = REPO_ROOT / "packages" / "installer" / "package.json"
OPENCLAW_PLUGIN_JSON = REPO_ROOT / "packages" / "openclaw-plugin" / "package.json"
LOCOMO_HANDOFF = (
    REPO_ROOT / "benchmarks" / "cross_agent" / "fixtures" / "locomo" / "handoff"
)
LOCOMO_SUMMARY = LOCOMO_HANDOFF / "matrix_summary_real.json"
README = REPO_ROOT / "README.md"
COMPAT_MATRIX = REPO_ROOT / "docs" / "agents" / "compatibility-matrix.md"
CROSS_AGENT_DOCS = REPO_ROOT / "docs" / "cross-agent-benchmarks.md"
RELEASE_NOTES = REPO_ROOT / "docs" / "RELEASE_NOTES_v2.0.4.md"

SUCCESS_STATUSES = frozenset({"completed"})
BLOCKED_STATUSES = frozenset(
    {"unsupported", "unavailable", "failed", "partial", "pending", "mock-only"},
)


def read_python_version() -> str:
    text = VERSION_PY.read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    if not match:
        raise SystemExit(f"Could not parse __version__ from {VERSION_PY}")
    return match.group(1)


def read_json_version(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    version = payload.get("version")
    if not isinstance(version, str):
        raise SystemExit(f"Invalid version in {path}")
    return version


def run_verify_release_versions() -> list[str]:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "verify_release_versions.py")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return [result.stderr.strip() or "verify_release_versions.py failed"]
    return []


def check_openclaw_plugin_version(python_version: str) -> list[str]:
    if not OPENCLAW_PLUGIN_JSON.is_file():
        return [f"Missing OpenClaw plugin package metadata: {OPENCLAW_PLUGIN_JSON}"]
    plugin_version = read_json_version(OPENCLAW_PLUGIN_JSON)
    if plugin_version != python_version:
        return [
            "OpenClaw plugin version mismatch: "
            f"@hm-arch/openclaw-plugin=={plugin_version} != hm-arch=={python_version}",
        ]
    peer = json.loads(OPENCLAW_PLUGIN_JSON.read_text(encoding="utf-8")).get(
        "peerDependencies",
        {},
    )
    openclaw_peer = peer.get("openclaw")
    if not isinstance(openclaw_peer, str) or not openclaw_peer:
        return ["@hm-arch/openclaw-plugin must declare openclaw peerDependency"]
    return []


def check_docs_mention_openclaw() -> list[str]:
    errors: list[str] = []
    readme = README.read_text(encoding="utf-8")
    compat = COMPAT_MATRIX.read_text(encoding="utf-8")
    if "OpenClaw" not in readme:
        errors.append("README.md does not mention OpenClaw")
    if "OpenClaw" not in compat:
        errors.append("docs/agents/compatibility-matrix.md does not mention OpenClaw")
    if "openclaw" not in readme.lower():
        errors.append("README.md does not document openclaw install commands")
    return errors


def check_release_notes() -> list[str]:
    if not RELEASE_NOTES.is_file():
        return [f"Missing release notes: {RELEASE_NOTES}"]
    text = RELEASE_NOTES.read_text(encoding="utf-8").lower()
    errors: list[str] = []
    required_phrases = [
        "openclaw",
        "benchmark",
        "limitation",
        "locomo",
    ]
    for phrase in required_phrases:
        if phrase not in text:
            errors.append(
                f"docs/RELEASE_NOTES_v2.0.4.md missing required topic: {phrase!r}",
            )
    if "three-agent" in text and "four-agent" not in text:
        errors.append(
            "Release notes still describe a three-agent line; OpenClaw must be listed",
        )
    return errors


def _cell_blocks_headline(cell: dict[str, Any]) -> bool:
    status = str(cell.get("status", "")).lower()
    runner_mode = str(cell.get("runner_mode", "")).lower()
    if status in BLOCKED_STATUSES:
        return True
    if runner_mode in {"mock-only", "unavailable", "unsupported"}:
        return True
    if cell.get("test_double_mode"):
        return True
    if status not in SUCCESS_STATUSES:
        return True
    completed = cell.get("completed_query_count")
    if completed is not None and int(completed) <= 0:
        return True
    return False


def validate_locomo_handoff() -> list[str]:
    if not LOCOMO_SUMMARY.is_file():
        return [f"Missing committed LoCoMo handoff artifact: {LOCOMO_SUMMARY}"]

    summary = json.loads(LOCOMO_SUMMARY.read_text(encoding="utf-8"))
    errors: list[str] = []

    if summary.get("test_double_mode"):
        errors.append("LoCoMo handoff uses test_double_mode=true (not production CLI)")
    if summary.get("report_type") != "real_cli_comparison":
        errors.append("LoCoMo handoff report_type is not real_cli_comparison")
    if not summary.get("provenance", {}).get("exact_command"):
        errors.append("LoCoMo handoff missing provenance.exact_command")

    cells = summary.get("cells", [])
    if not cells:
        errors.append("LoCoMo handoff matrix has no cells")

    headline_candidates = [
        cell
        for cell in cells
        if cell.get("backend") in {"no_memory", "hm_arch"}
        and cell.get("agent") in {"openclaw", "hermes", "claude_code", "codex"}
    ]
    completed = [cell for cell in headline_candidates if cell.get("status") == "completed"]
    blocked_presented_as_success = [
        cell["coordinate"]
        for cell in headline_candidates
        if _cell_blocks_headline(cell) and cell.get("mean_accuracy") not in (None, 0.0)
    ]
    if blocked_presented_as_success:
        errors.append(
            "LoCoMo cells present blocked statuses with non-null accuracy claims: "
            + ", ".join(blocked_presented_as_success),
        )

    for cell in cells:
        summary_path = cell.get("summary_path")
        if not summary_path:
            continue
        path = REPO_ROOT / summary_path
        if cell.get("status") in {"completed", "partial", "failed", "unavailable"}:
            if not path.is_file():
                errors.append(f"LoCoMo cell references missing summary: {summary_path}")

    openclaw_cells = [c for c in cells if c.get("agent") == "openclaw"]
    if not openclaw_cells:
        errors.append("LoCoMo handoff matrix missing OpenClaw rows")
    for cell in openclaw_cells:
        if cell.get("status") == "completed" and cell.get("runner_mode") != "real":
            errors.append(
                f"OpenClaw cell {cell.get('coordinate')} marked completed without real runner",
            )

    notes = [
        f"LoCoMo handoff: {len(completed)} completed real cells, "
        f"{len(headline_candidates) - len(completed)} blocked/failed/unavailable",
    ]
    return errors + [f"INFO: {note}" for note in notes]


def check_uncommitted_benchmark_docs() -> list[str]:
    """Ensure docs do not claim committed hotpotqa/tau2 artifacts that are absent."""
    errors: list[str] = []
    cross_agent = CROSS_AGENT_DOCS.read_text(encoding="utf-8")
    hotpotqa_path = REPO_ROOT / "benchmark-results" / "hotpotqa" / "matrix_summary.json"
    tau2_path = REPO_ROOT / "benchmark-results" / "tau2-comparison" / "matrix_summary.json"

    if "benchmark-results/hotpotqa/" in cross_agent and not hotpotqa_path.is_file():
        if "not committed" not in cross_agent.lower() and "gitignored" not in cross_agent:
            errors.append(
                "cross-agent-benchmarks.md references benchmark-results/hotpotqa/ "
                "but no committed artifact exists; document as local-only output",
            )
    if "benchmark-results/tau2-comparison/" in cross_agent and not tau2_path.is_file():
        if "not committed" not in cross_agent.lower() and "gitignored" not in cross_agent:
            errors.append(
                "cross-agent-benchmarks.md references benchmark-results/tau2-comparison/ "
                "but no committed artifact exists; document as local-only output",
            )
    return errors


def main() -> int:
    errors: list[str] = []
    python_version = read_python_version()

    errors.extend(run_verify_release_versions())
    errors.extend(check_openclaw_plugin_version(python_version))
    errors.extend(check_docs_mention_openclaw())
    errors.extend(check_release_notes())
    errors.extend(validate_locomo_handoff())
    errors.extend(check_uncommitted_benchmark_docs())

    info_lines = [line[6:] for line in errors if line.startswith("INFO: ")]
    errors = [line for line in errors if not line.startswith("INFO: ")]

    if errors:
        print("Release gate validation FAILED:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(
        "Release gate validation OK: "
        f"hm-arch=={python_version}, OpenClaw integration documented, "
        "LoCoMo handoff artifacts audited",
    )
    for line in info_lines:
        print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
