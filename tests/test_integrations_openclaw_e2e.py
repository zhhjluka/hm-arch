"""End-to-end OpenClaw integration tests (MEM-75 / HM-74).

Exercises the canonical installer, plugin payload, management CLI, and Python
sidecar together in isolated OpenClaw homes. No test touches real user OpenClaw
data under ``~/.openclaw``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from hm_arch import HMArch
from hm_arch._version import __version__
from hm_arch.integrations.cli.main import main
from hm_arch.integrations.management.openclaw import OpenClawAgentHandler
from hm_arch.integrations.openclaw.config import (
    HM_ARCH_PLUGIN_ID,
    load_openclaw_config,
    read_memory_slot,
    resolve_db_path,
    resolve_openclaw_config_path,
)
from hm_arch.integrations.openclaw.sidecar import SidecarServer
from hm_arch.integrations.sidecar.protocol import CURRENT_PROTOCOL_VERSION

_REPO_ROOT = Path(__file__).resolve().parents[1]
_E2E_ARTIFACTS = _REPO_ROOT / "artifacts" / "openclaw-e2e"


def _request(operation: str, params: dict[str, Any], *, correlation_id: str) -> str:
    return json.dumps(
        {
            "protocol_version": CURRENT_PROTOCOL_VERSION,
            "correlation_id": correlation_id,
            "operation": operation,
            "params": params,
        },
        ensure_ascii=False,
    )


def _initialize(db_path: str, *, correlation_id: str = "e2e-init") -> str:
    return _request(
        "initialize",
        {
            "db_path": db_path,
            "client_capabilities": ["telemetry.v1", "forget.by_query.v1"],
            "config": {"preset": "code_agent"},
        },
        correlation_id=correlation_id,
    )


def _parse_sidecar_line(server: SidecarServer, payload: str) -> dict[str, Any]:
    return json.loads(server.handle_line(payload))


@pytest.fixture()
def isolated_openclaw_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    state_dir = home / ".openclaw"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(state_dir))
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.chdir(project_root)
    return project_root


class TestOpenClawE2EInstallAndLifecycle:
    def test_isolated_install_store_restart_recall_uninstall(
        self,
        isolated_openclaw_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        config_path = isolated_openclaw_home / ".openclaw" / "openclaw.json"
        plugin_dir = config_path.parent / "extensions" / HM_ARCH_PLUGIN_ID

        assert main(["install", "openclaw"]) == 0
        install_err = capsys.readouterr().err
        assert "openclaw (project): installed" in install_err
        assert plugin_dir.is_dir()
        assert (plugin_dir / "openclaw.plugin.json").is_file()
        assert (plugin_dir / "dist" / "index.js").is_file()

        config = load_openclaw_config(config_path)
        assert read_memory_slot(config) == HM_ARCH_PLUGIN_ID
        db_path = resolve_db_path(config_path.parent, config["plugins"]["entries"][HM_ARCH_PLUGIN_ID]["config"])

        marker = "e2e install store restart recall marker"
        first = SidecarServer()
        _parse_sidecar_line(first, _initialize(db_path, correlation_id="e2e-init-1"))
        remember = _parse_sidecar_line(
            first,
            _request(
                "remember",
                {"content": marker, "importance": 0.9},
                correlation_id="e2e-remember",
            ),
        )
        assert remember["ok"] is True
        _parse_sidecar_line(first, _request("shutdown", {}, correlation_id="e2e-shutdown-1"))

        second = SidecarServer()
        _parse_sidecar_line(second, _initialize(db_path, correlation_id="e2e-restart-init"))
        search = _parse_sidecar_line(
            second,
            _request(
                "search",
                {"query": "install store restart recall", "top_k": 5},
                correlation_id="e2e-search",
            ),
        )
        assert search["ok"] is True
        assert search["result"]["result_count"] >= 1
        telemetry = search["telemetry"]
        assert telemetry["query_latency_ms"] >= 0
        assert telemetry["returned_tokens"] >= 0
        assert telemetry["returned_characters"] >= 0
        assert any(marker in str(hit.get("content", "")) for hit in search["result"]["hits"])

        assert main(["status", "openclaw"]) == 0
        assert main(["doctor", "openclaw"]) == 0
        assert main(["uninstall", "openclaw"]) == 0
        uninstall_err = capsys.readouterr().err
        assert "openclaw (project): not_installed" in uninstall_err
        assert not plugin_dir.exists()
        assert Path(db_path).exists()

    def test_memory_slot_conflict_diagnostics(
        self,
        isolated_openclaw_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        config_path = isolated_openclaw_home / ".openclaw" / "openclaw.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            json.dumps(
                {
                    "plugins": {
                        "slots": {"memory": "memory-lancedb"},
                        "entries": {
                            "memory-lancedb": {"enabled": True, "config": {}},
                        },
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        assert main(["status", "openclaw"]) == 1
        err = capsys.readouterr().err
        assert "conflict" in err.lower() or "memory-lancedb" in err

        report = OpenClawAgentHandler().install(global_install=False)
        assert report.state.value == "partial"
        assert any("conflict" in item.message.lower() for item in report.diagnostics)


class TestOpenClawE2ESidecarBehavior:
    def test_recall_and_capture_failures_remain_non_fatal(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "fail-open.db")
        server = SidecarServer()
        _parse_sidecar_line(server, _initialize(db_path))

        failed_search = _parse_sidecar_line(
            server,
            _request("search", {"query": ""}, correlation_id="bad-search"),
        )
        assert failed_search["ok"] is False
        assert failed_search["result"]["result_count"] == 0

        ok_remember = _parse_sidecar_line(
            server,
            _request(
                "remember",
                {"content": "still writable after failed search"},
                correlation_id="remember-after-fail",
            ),
        )
        assert ok_remember["ok"] is True

    def test_shared_store_visible_to_openclaw_sidecar(self, tmp_path: Path) -> None:
        db_path = tmp_path / "shared.db"
        shared_fact = "Codex agent prefers pytest markers for offline suites"
        with HMArch(db_path=str(db_path)) as memory:
            memory.add(shared_fact, agent="codex", project="/tmp/shared-project")

        server = SidecarServer()
        _parse_sidecar_line(server, _initialize(str(db_path), correlation_id="shared-init"))
        search = _parse_sidecar_line(
            server,
            _request(
                "search",
                {"query": "pytest markers offline", "top_k": 5},
                correlation_id="shared-search",
            ),
        )
        assert search["ok"] is True
        assert search["result"]["result_count"] >= 1
        assert any("pytest markers" in str(hit.get("content", "")) for hit in search["result"]["hits"])


class TestOpenClawE2EPackagingPaths:
    def test_python_wheel_install_path(self, tmp_path: Path) -> None:
        pytest.importorskip("build")
        from tests.test_integrations_openclaw_wheel import (
            _build_wheel,
            _install_wheel_to_target,
            _run_hm_arch,
        )

        isolated_root = tmp_path / "wheel-e2e"
        dist_dir = isolated_root / "dist"
        dist_dir.mkdir(parents=True)
        workdir = isolated_root / "workdir"
        workdir.mkdir()
        home = isolated_root / "home"
        home.mkdir()
        site_packages = isolated_root / "site-packages"
        site_packages.mkdir()

        wheel_path = _build_wheel(dist_dir)
        _install_wheel_to_target(wheel_path, site_packages)
        state_dir = home / ".openclaw"
        env = {
            "HOME": str(home),
            "OPENCLAW_STATE_DIR": str(state_dir),
            "PYTHONPATH": str(site_packages),
            "PYTHONNOUSERSITE": "1",
        }
        install = _run_hm_arch(["install", "openclaw"], env=env, cwd=workdir)
        assert install.returncode == 0, install.stderr
        config_path = workdir / ".openclaw" / "openclaw.json"
        assert config_path.exists()
        config = json.loads(config_path.read_text(encoding="utf-8"))
        assert config["plugins"]["slots"]["memory"] == HM_ARCH_PLUGIN_ID

    def test_npm_installer_openclaw_path_when_available(self, tmp_path: Path) -> None:
        installer_dir = _REPO_ROOT / "packages" / "installer"
        if not (installer_dir / "package.json").is_file():
            pytest.skip("npm installer package not present")
        if shutil.which("npm") is None:
            pytest.skip("npm not available")

        build = subprocess.run(
            ["npm", "run", "build"],
            cwd=installer_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if build.returncode != 0:
            pytest.skip(f"npm build failed: {build.stderr}")

        home = tmp_path / "home"
        workdir = tmp_path / "workdir"
        home.mkdir()
        workdir.mkdir()
        state_dir = home / "openclaw-state"
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "OPENCLAW_STATE_DIR": str(state_dir),
                "HM_ARCH_HOME": str(home / "hm-arch-home"),
                "HM_ARCH_PYTHON": sys.executable,
                "HM_ARCH_PIP_SPEC": str(_REPO_ROOT),
            }
        )
        cli = installer_dir / "dist" / "cli.js"
        install = subprocess.run(
            ["node", str(cli), "install", "openclaw"],
            cwd=workdir,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert install.returncode == 0, install.stderr
        plugin_dir = workdir / ".openclaw" / "extensions" / HM_ARCH_PLUGIN_ID
        assert plugin_dir.is_dir()
        assert (plugin_dir / "dist" / "index.js").is_file()


def write_e2e_artifact_report(
    *,
    hm_arch_version: str,
    python_version: str,
    node_version: str | None,
    openclaw_config_path: str | None = None,
    notes: list[str] | None = None,
) -> Path:
    """Write a machine-readable E2E handoff artifact for CI or local runs."""
    _E2E_ARTIFACTS.mkdir(parents=True, exist_ok=True)
    payload = {
        "hm_arch_version": hm_arch_version,
        "python_version": python_version,
        "node_version": node_version,
        "openclaw_config_path": openclaw_config_path,
        "notes": notes or [],
    }
    report_path = _E2E_ARTIFACTS / "report.json"
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return report_path


def test_e2e_handoff_artifact_metadata() -> None:
    node_version: str | None
    try:
        proc = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        node_version = proc.stdout.strip() if proc.returncode == 0 else None
    except OSError:
        node_version = None

    with tempfile.TemporaryDirectory(prefix="hm-arch-openclaw-e2e-") as tmp:
        config_path = Path(tmp) / "openclaw.json"
        config_path.write_text("{}", encoding="utf-8")
        report = write_e2e_artifact_report(
            hm_arch_version=__version__,
            python_version=sys.version.split()[0],
            node_version=node_version,
            openclaw_config_path=str(config_path),
            notes=["isolated OpenClaw home only"],
        )
        data = json.loads(report.read_text(encoding="utf-8"))
        assert data["hm_arch_version"] == __version__
        assert data["openclaw_config_path"].endswith("openclaw.json")
