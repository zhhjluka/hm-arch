"""Offline tests for standalone release artifact naming and checksums (MEM-62)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.prepare_release_artifacts import (  # noqa: E402
    artifact_record,
    prepare_release_artifact,
    sha256_file,
    write_checksum_file,
    write_release_metadata,
    write_sha256sums,
)
from scripts.release_artifact_naming import (  # noqa: E402
    ReleaseTarget,
    detect_release_target,
    is_supported_target,
    normalize_arch,
    normalize_os,
    parse_artifact_filename,
    supported_release_targets,
)
from scripts.validate_release_artifacts import (  # noqa: E402
    validate_checksum_file,
    validate_metadata,
)


def test_supported_release_targets_cover_primary_platforms() -> None:
    targets = supported_release_targets()
    suffixes = {target.artifact_suffix() for target in targets}
    assert "linux-x86_64" in suffixes
    assert "linux-aarch64" in suffixes
    assert "darwin-arm64" in suffixes
    assert "darwin-x86_64" in suffixes
    assert "windows-x86_64" in suffixes


@pytest.mark.parametrize(
    ("machine", "system", "expected_arch"),
    [
        ("x86_64", "Linux", "x86_64"),
        ("AMD64", "Windows", "x86_64"),
        ("aarch64", "Linux", "aarch64"),
        ("arm64", "Darwin", "arm64"),
    ],
)
def test_normalize_arch_and_os(machine: str, system: str, expected_arch: str) -> None:
    os_name = normalize_os(system)
    assert normalize_arch(machine, os_name=os_name) == expected_arch
    assert os_name in {"linux", "darwin", "windows"}


def test_release_target_filename_includes_version_and_platform() -> None:
    target = ReleaseTarget("linux", "x86_64")
    assert target.filename("1.2.3") == "hm-arch-1.2.3-linux-x86_64"
    windows = ReleaseTarget("windows", "x86_64")
    assert windows.filename("1.2.3") == "hm-arch-1.2.3-windows-x86_64.exe"


def test_parse_artifact_filename_round_trip() -> None:
    target = ReleaseTarget("darwin", "arm64")
    filename = target.filename("1.0.0")
    version, parsed = parse_artifact_filename(filename)
    assert version == "1.0.0"
    assert parsed == target


def test_detect_release_target_is_supported() -> None:
    target = detect_release_target()
    assert is_supported_target(target)


def test_prepare_checksum_and_metadata_round_trip(tmp_path: Path) -> None:
    built = tmp_path / "hm-arch"
    built.write_bytes(b"standalone-binary-payload")
    built.chmod(0o755)
    output_dir = tmp_path / "release"
    target = ReleaseTarget("linux", "x86_64")
    version = "9.9.9"

    artifact_path = prepare_release_artifact(
        built_executable=built,
        output_dir=output_dir,
        version=version,
        target=target,
    )
    checksum_path = write_checksum_file(artifact_path)
    metadata_path = write_release_metadata(
        output_dir=output_dir,
        version=version,
        artifacts=[artifact_record(artifact_path, version=version, target=target)],
    )
    sums_path = write_sha256sums(output_dir, [artifact_path])

    validate_checksum_file(artifact_path)
    validate_metadata(metadata_path, output_dir)

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["version"] == version
    assert metadata["artifacts"][0]["filename"] == artifact_path.name
    assert metadata["artifacts"][0]["sha256"] == sha256_file(artifact_path)

    sums_text = sums_path.read_text(encoding="utf-8")
    assert artifact_path.name in sums_text
    assert checksum_path.read_text(encoding="utf-8").startswith(metadata["artifacts"][0]["sha256"])
