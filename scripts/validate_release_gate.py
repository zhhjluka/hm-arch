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
HOTPOTQA_ROOT = REPO_ROOT / "benchmark-results" / "hotpotqa"
HOTPOTQA_SUMMARY = HOTPOTQA_ROOT / "matrix_summary.json"
TAU2_ROOT = REPO_ROOT / "benchmark-results" / "tau2-comparison"
TAU2_MATRIX_STATUS = TAU2_ROOT / "matrix_status.json"
TAU2_SUMMARY_TABLE = TAU2_ROOT / "summary_table.json"
TAU2_PROVENANCE = TAU2_ROOT / "provenance.json"
README = REPO_ROOT / "README.md"
COMPAT_MATRIX = REPO_ROOT / "docs" / "agents" / "compatibility-matrix.md"
CROSS_AGENT_DOCS = REPO_ROOT / "docs" / "cross-agent-benchmarks.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

SUCCESS_STATUSES = frozenset({"completed"})
BLOCKED_STATUSES = frozenset(
    {
        "unsupported",
        "unavailable",
        "failed",
        "partial",
        "pending",
        "mock-only",
        "run",
    },
)
FALSE_SUCCESS_STATUSES = frozenset(
    {"unsupported", "unavailable", "mock-only", "pending"},
)


def read_python_version() -> str:
    text = VERSION_PY.read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    if not match:
        raise SystemExit(f"Could not parse __version__ from {VERSION_PY}")
    return match.group(1)


def release_notes_path(version: str) -> Path:
    return REPO_ROOT / "docs" / f"RELEASE_NOTES_v{version}.md"


def read_json_version(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    version = payload.get("version")
    if not isinstance(version, str):
        raise SystemExit(f"Invalid version in {path}")
    return version


def is_git_tracked(path: Path) -> bool:
    if not path.is_file():
        return False
    rel = path.relative_to(REPO_ROOT).as_posix()
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", rel],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def git_tag_exists(version: str) -> bool:
    result = subprocess.run(
        ["git", "tag", "-l", f"v{version}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(result.stdout.strip())


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


def check_version_not_already_published(version: str) -> list[str]:
    if git_tag_exists(version):
        return [
            f"Release version {version} is already published as git tag v{version}; "
            "bump src/hm_arch/_version.py before running the release gate",
        ]
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


def check_release_notes(version: str) -> list[str]:
    release_notes = release_notes_path(version)
    if not release_notes.is_file():
        return [f"Missing release notes: {release_notes}"]
    text = release_notes.read_text(encoding="utf-8").lower()
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
                f"{release_notes.name} missing required topic: {phrase!r}",
            )
    if "three-agent" in text and "four-agent" not in text:
        errors.append(
            f"{release_notes.name} still describes a three-agent line; "
            "OpenClaw must be listed",
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
    if cell.get("use_mock_agent"):
        return True
    if status not in SUCCESS_STATUSES:
        return True
    completed = cell.get("completed_query_count")
    if completed is not None and int(completed) <= 0:
        return True
    return False


def _blocked_cells_with_metric_claims(
    cells: list[dict[str, Any]],
    *,
    metric_keys: tuple[str, ...] = ("mean_accuracy",),
    statuses: frozenset[str] = FALSE_SUCCESS_STATUSES,
) -> list[str]:
    blocked: list[str] = []
    for cell in cells:
        status = str(cell.get("status", "")).lower()
        if status not in statuses and not cell.get("use_mock_agent") and not cell.get(
            "test_double_mode",
        ):
            continue
        coordinate = cell.get("coordinate") or (
            f"{cell.get('agent')}/{cell.get('backend')}"
            + (f" k{cell['top_k']}" if cell.get("top_k") is not None else "")
        )
        for key in metric_keys:
            value = cell.get(key)
            if value is None:
                continue
            if isinstance(value, (int, float)) and float(value) == 0.0:
                continue
            blocked.append(f"{coordinate} ({key}={value}, status={status})")
            break
    return blocked


def validate_locomo_handoff() -> list[str]:
    if not LOCOMO_SUMMARY.is_file():
        return [f"Missing committed LoCoMo handoff artifact: {LOCOMO_SUMMARY}"]
    if not is_git_tracked(LOCOMO_SUMMARY):
        return [f"LoCoMo handoff artifact is not git-tracked: {LOCOMO_SUMMARY}"]

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
        coord
        for cell in headline_candidates
        for coord in _blocked_cells_with_metric_claims(
            [cell],
            statuses=FALSE_SUCCESS_STATUSES,
        )
    ]
    blocked_presented_as_success.extend(
        [
            f"{cell.get('coordinate')} (status={cell.get('status')})"
            for cell in headline_candidates
            if _cell_blocks_headline(cell)
            and cell.get("status") not in FALSE_SUCCESS_STATUSES
            and cell.get("mean_accuracy") not in (None, 0.0)
            and cell.get("status") != "completed"
        ],
    )
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


def _classify_hotpotqa_cell_outcome(cell: dict[str, Any]) -> str:
    """Derive pilot outcome from HotpotQA matrix_summary cell schema."""
    status = str(cell.get("status", "")).lower()
    if status in {"unsupported", "pending", "completed", "failed"}:
        return status
    if status == "run":
        completed = int(cell.get("completed_query_count") or 0)
        failures = int(cell.get("total_failure_count") or 0)
        if completed > 0 and failures == 0:
            return "completed"
        if failures > 0:
            return "failed"
        return "run"
    return status or "unknown"


def _derive_hotpotqa_counts(cells: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"completed": 0, "failed": 0, "pending": 0, "unsupported": 0, "run": 0}
    for cell in cells:
        outcome = _classify_hotpotqa_cell_outcome(cell)
        if outcome in counts:
            counts[outcome] += 1
    return counts


def _hotpotqa_top_level_counter_keys() -> dict[str, str]:
    return {
        "completed": "completed_cells",
        "failed": "failed_cells",
        "pending": "pending_cells",
        "unsupported": "unsupported_cells",
    }


def validate_hotpotqa_artifacts() -> list[str]:
    errors: list[str] = []
    if not HOTPOTQA_SUMMARY.is_file():
        return [f"Missing HotpotQA matrix summary: {HOTPOTQA_SUMMARY}"]
    if not is_git_tracked(HOTPOTQA_SUMMARY):
        errors.append(f"HotpotQA matrix summary is not git-tracked: {HOTPOTQA_SUMMARY}")

    summary = json.loads(HOTPOTQA_SUMMARY.read_text(encoding="utf-8"))
    cells = summary.get("cells", [])
    if not cells:
        errors.append("HotpotQA matrix_summary.json has no cells")

    derived = _derive_hotpotqa_counts(cells)
    for outcome, summary_key in _hotpotqa_top_level_counter_keys().items():
        expected = summary.get(summary_key)
        if expected is None:
            errors.append(f"HotpotQA matrix_summary.json missing top-level {summary_key}")
            continue
        if int(expected) != derived[outcome]:
            errors.append(
                f"HotpotQA {summary_key}={expected} does not match derived "
                f"{outcome} count {derived[outcome]} from cell schema",
            )

    if derived["run"] > 0:
        errors.append(
            f"HotpotQA has {derived['run']} ambiguous run cells that could not be "
            "classified as completed or failed",
        )

    blocked_with_claims = _blocked_cells_with_metric_claims(
        cells,
        metric_keys=("mean_accuracy", "mean_retrieval_hit_rate"),
    )
    if blocked_with_claims:
        errors.append(
            "HotpotQA cells present blocked statuses with metric claims: "
            + ", ".join(blocked_with_claims),
        )

    if summary.get("use_mock_agent"):
        errors.append("HotpotQA committed artifact uses use_mock_agent=true")

    notes = [
        "HotpotQA pilot: "
        f"{derived['completed']} completed, {derived['failed']} failed, "
        f"{derived['pending']} pending, {derived['unsupported']} unsupported "
        "(derived from status=run query outcomes)",
    ]
    if derived["pending"] or derived["unsupported"] or derived["failed"]:
        notes.append(
            "HotpotQA pilot is incomplete; do not publish headline comparisons",
        )
    return errors + [f"INFO: {note}" for note in notes]


def validate_tau2_artifacts() -> list[str]:
    errors: list[str] = []
    required = [
        (TAU2_MATRIX_STATUS, "matrix_status.json"),
        (TAU2_SUMMARY_TABLE, "summary_table.json"),
        (TAU2_PROVENANCE, "provenance.json"),
    ]
    for path, label in required:
        if not path.is_file():
            errors.append(f"Missing tau2-bench artifact: {path}")
            continue
        if not is_git_tracked(path):
            errors.append(f"tau2-bench {label} is not git-tracked: {path}")

    if errors:
        return errors

    matrix_status = json.loads(TAU2_MATRIX_STATUS.read_text(encoding="utf-8"))
    summary_table = json.loads(TAU2_SUMMARY_TABLE.read_text(encoding="utf-8"))
    provenance = json.loads(TAU2_PROVENANCE.read_text(encoding="utf-8"))

    if provenance.get("tau2_importable") is False:
        notes = ["tau2-bench: tau2_importable=false (availability record only)"]
    else:
        notes = ["tau2-bench: tau2_importable=true"]

    completed_cells = [
        cell for cell in matrix_status if cell.get("status") == "completed"
    ]
    if completed_cells:
        errors.append(
            "tau2-bench matrix_status.json reports completed cells without a "
            "production-ready pilot; audit before release",
        )

    blocked_rows: list[str] = []
    for row in summary_table.get("rows", []):
        status = str(row.get("status", "")).lower()
        excluded = row.get("excluded_from_benchmark_table", False)
        metric_keys = (
            "retail_task_success_rate",
            "retail_mean_accuracy",
            "airline_task_success_rate",
            "airline_mean_accuracy",
            "mean_query_time_ms",
        )
        has_metric = any(row.get(key) not in (None, 0, 0.0) for key in metric_keys)
        if status in BLOCKED_STATUSES or excluded:
            if has_metric:
                blocked_rows.append(
                    f"{row.get('agent')}/{row.get('backend')} "
                    f"(status={status}, excluded={excluded})",
                )
        elif status not in SUCCESS_STATUSES and has_metric:
            blocked_rows.append(f"{row.get('agent')}/{row.get('backend')} (status={status})")

    if blocked_rows:
        errors.append(
            "tau2-bench summary_table rows present blocked statuses with metric claims: "
            + ", ".join(blocked_rows),
        )

    notes.append(
        f"tau2-bench matrix: {len(completed_cells)} completed cells, "
        f"{len(matrix_status)} total status rows",
    )
    return errors + [f"INFO: {note}" for note in notes]


def check_benchmark_doc_claims() -> list[str]:
    """Reject docs that falsely claim HotpotQA/tau2 artifacts are uncommitted."""
    errors: list[str] = []
    cross_agent = CROSS_AGENT_DOCS.read_text(encoding="utf-8")
    changelog = CHANGELOG.read_text(encoding="utf-8")
    lower_cross = cross_agent.lower()

    hotpotqa_tracked = is_git_tracked(HOTPOTQA_SUMMARY)
    tau2_tracked = is_git_tracked(TAU2_MATRIX_STATUS)

    false_uncommitted_phrases = (
        "not committed",
        "local only",
        "gitignored",
        "no committed production matrix",
    )

    if hotpotqa_tracked:
        for phrase in false_uncommitted_phrases:
            hotpotqa_context = re.search(
                rf"hotpotqa[^\n]{{0,200}}{re.escape(phrase)}",
                lower_cross,
                flags=re.IGNORECASE,
            )
            if hotpotqa_context:
                errors.append(
                    "cross-agent-benchmarks.md falsely claims HotpotQA artifacts are "
                    f"uncommitted ({phrase!r}); "
                    f"{HOTPOTQA_SUMMARY.relative_to(REPO_ROOT)} is git-tracked",
                )
                break
        if "incomplete pilot" not in lower_cross and "partial matrix" not in lower_cross:
            errors.append(
                "cross-agent-benchmarks.md must document HotpotQA committed pilot "
                "as incomplete/partial",
            )
        if "status=run" not in lower_cross.replace(" ", "") and "status=`run`" not in lower_cross:
            errors.append(
                "cross-agent-benchmarks.md must document HotpotQA run-row outcome encoding",
            )

    if tau2_tracked:
        for phrase in false_uncommitted_phrases:
            tau2_context = re.search(
                rf"tau2[^\n]{{0,200}}{re.escape(phrase)}",
                lower_cross,
                flags=re.IGNORECASE,
            )
            if tau2_context:
                errors.append(
                    "cross-agent-benchmarks.md falsely claims tau2-bench artifacts are "
                    f"uncommitted ({phrase!r}); "
                    f"{TAU2_ROOT.relative_to(REPO_ROOT)} is git-tracked",
                )
                break
        if (
            "availability record" not in lower_cross
            and "tau2_importable" not in lower_cross
        ):
            errors.append(
                "cross-agent-benchmarks.md must document tau2-bench committed "
                "artifact pilot/availability status",
            )

    if hotpotqa_tracked and "still pending" in changelog.lower():
        if re.search(r"hotpotqa[^\n]*still pending", changelog, flags=re.IGNORECASE):
            errors.append(
                "CHANGELOG.md falsely claims HotpotQA committed artifacts are still pending",
            )

    return errors


def main() -> int:
    errors: list[str] = []
    python_version = read_python_version()

    errors.extend(check_version_not_already_published(python_version))
    errors.extend(run_verify_release_versions())
    errors.extend(check_openclaw_plugin_version(python_version))
    errors.extend(check_docs_mention_openclaw())
    errors.extend(check_release_notes(python_version))
    errors.extend(validate_locomo_handoff())
    errors.extend(validate_hotpotqa_artifacts())
    errors.extend(validate_tau2_artifacts())
    errors.extend(check_benchmark_doc_claims())

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
        "LoCoMo/HotpotQA/tau2 benchmark artifacts audited",
    )
    for line in info_lines:
        print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
