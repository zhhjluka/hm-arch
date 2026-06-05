#!/usr/bin/env python3
"""Validate standalone release artifact checksums and metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.release_artifact_naming import parse_artifact_filename  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_sha256sums(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        digest, filename = stripped.split(maxsplit=1)
        entries[filename.strip()] = digest
    return entries


def validate_checksum_file(artifact_path: Path) -> None:
    checksum_path = artifact_path.with_suffix(artifact_path.suffix + ".sha256")
    if not checksum_path.is_file():
        raise FileNotFoundError(f"Missing checksum file: {checksum_path}")
    expected_line = checksum_path.read_text(encoding="utf-8").strip()
    expected_digest, expected_name = expected_line.split(maxsplit=1)
    if expected_name != artifact_path.name:
        raise ValueError(
            f"Checksum filename mismatch: {expected_name} != {artifact_path.name}",
        )
    actual_digest = sha256_file(artifact_path)
    if actual_digest != expected_digest:
        raise ValueError(
            f"Checksum mismatch for {artifact_path.name}: "
            f"expected {expected_digest}, got {actual_digest}",
        )


def validate_metadata(metadata_path: Path, artifacts_dir: Path) -> None:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    for record in metadata.get("artifacts", []):
        filename = record["filename"]
        artifact_path = artifacts_dir / filename
        if not artifact_path.is_file():
            raise FileNotFoundError(f"Metadata references missing artifact: {artifact_path}")
        actual_digest = sha256_file(artifact_path)
        if actual_digest != record["sha256"]:
            raise ValueError(f"Metadata checksum mismatch for {filename}")
        actual_size = artifact_path.stat().st_size
        if actual_size != record["size_bytes"]:
            raise ValueError(f"Metadata size mismatch for {filename}")
        _, target = parse_artifact_filename(filename)
        if record["os"] != target.os_name or record["arch"] != target.arch:
            raise ValueError(f"Metadata target mismatch for {filename}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=_REPO_ROOT / "dist" / "release",
        help="Directory containing release artifacts.",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=None,
        help="Optional release metadata JSON path.",
    )
    parser.add_argument(
        "--sha256sums",
        type=Path,
        default=None,
        help="Optional SHA256SUMS file path.",
    )
    args = parser.parse_args(argv)

    artifacts_dir = args.artifacts_dir
    artifact_paths = sorted(
        path
        for path in artifacts_dir.glob("hm-arch-*")
        if path.is_file()
        and not path.name.endswith(".sha256")
        and not path.name.endswith("-standalone-release-metadata.json")
    )
    if not artifact_paths:
        raise SystemExit(f"No artifacts found in {artifacts_dir}")

    for artifact_path in artifact_paths:
        validate_checksum_file(artifact_path)

    sums_path = args.sha256sums or (artifacts_dir / "SHA256SUMS")
    if sums_path.is_file():
        entries = parse_sha256sums(sums_path)
        for artifact_path in artifact_paths:
            expected = entries.get(artifact_path.name)
            if expected is None:
                raise ValueError(f"SHA256SUMS missing entry for {artifact_path.name}")
            if expected != sha256_file(artifact_path):
                raise ValueError(f"SHA256SUMS mismatch for {artifact_path.name}")

    metadata_path = args.metadata
    if metadata_path is None:
        candidates = sorted(artifacts_dir.glob("hm-arch-*-standalone-release-metadata.json"))
        metadata_path = candidates[-1] if candidates else None
    if metadata_path and metadata_path.is_file():
        validate_metadata(metadata_path, artifacts_dir)

    print(f"Validated {len(artifact_paths)} release artifact(s) in {artifacts_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
