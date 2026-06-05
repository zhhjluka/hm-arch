#!/usr/bin/env python3
"""Prepare versioned standalone release artifacts, checksums, and metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.release_artifact_naming import (  # noqa: E402
    ReleaseTarget,
    detect_release_target,
    is_supported_target,
    parse_artifact_filename,
)


def _repo_root() -> Path:
    return _REPO_ROOT


def _read_version(repo_root: Path) -> str:
    version_path = repo_root / "src" / "hm_arch" / "_version.py"
    text = version_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip("\"'")
    raise RuntimeError(f"Could not read __version__ from {version_path}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def default_built_executable(repo_root: Path) -> Path:
    if sys.platform == "win32":
        return repo_root / "dist" / "standalone" / "hm-arch.exe"
    return repo_root / "dist" / "standalone" / "hm-arch"


def prepare_release_artifact(
    *,
    built_executable: Path,
    output_dir: Path,
    version: str,
    target: ReleaseTarget,
) -> Path:
    if not built_executable.is_file():
        raise FileNotFoundError(f"Built executable not found: {built_executable}")
    if not is_supported_target(target):
        raise ValueError(f"Unsupported release target: {target}")

    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / target.filename(version)
    shutil.copy2(built_executable, destination)
    if sys.platform != "win32" and target.os_name != "windows":
        destination.chmod(destination.stat().st_mode | 0o111)
    return destination


def write_checksum_file(artifact_path: Path) -> Path:
    checksum_path = artifact_path.with_suffix(artifact_path.suffix + ".sha256")
    digest = sha256_file(artifact_path)
    checksum_path.write_text(f"{digest}  {artifact_path.name}\n", encoding="utf-8")
    return checksum_path


def artifact_record(artifact_path: Path, *, version: str, target: ReleaseTarget) -> dict:
    return {
        "filename": artifact_path.name,
        "os": target.os_name,
        "arch": target.arch,
        "version": version,
        "sha256": sha256_file(artifact_path),
        "size_bytes": artifact_path.stat().st_size,
    }


def write_release_metadata(
    *,
    output_dir: Path,
    version: str,
    artifacts: list[dict],
) -> Path:
    metadata = {
        "schema_version": 1,
        "package": "hm-arch",
        "version": version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": sorted(artifacts, key=lambda item: item["filename"]),
    }
    metadata_path = output_dir / f"hm-arch-{version}-standalone-release-metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata_path


def write_sha256sums(output_dir: Path, artifact_paths: list[Path]) -> Path:
    lines = []
    for artifact_path in sorted(artifact_paths, key=lambda path: path.name):
        lines.append(f"{sha256_file(artifact_path)}  {artifact_path.name}")
    sums_path = output_dir / "SHA256SUMS"
    sums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return sums_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--built-executable",
        type=Path,
        default=None,
        help="Path to the PyInstaller-built executable.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for versioned artifacts and metadata (default: dist/release).",
    )
    parser.add_argument("--version", default=None, help="Release version (default: package version).")
    parser.add_argument("--os-name", default=None, help="Target OS name (linux, darwin, windows).")
    parser.add_argument("--arch", default=None, help="Target CPU arch (x86_64, aarch64, arm64).")
    parser.add_argument(
        "--merge-metadata",
        action="store_true",
        help="Merge existing artifact records in output-dir into release metadata.",
    )
    args = parser.parse_args(argv)

    repo_root = _repo_root()
    version = args.version or _read_version(repo_root)
    output_dir = args.output_dir or (repo_root / "dist" / "release")
    built_executable = args.built_executable or default_built_executable(repo_root)

    if args.merge_metadata:
        artifact_paths = sorted(
            path
            for path in output_dir.glob(f"hm-arch-{version}-*")
            if path.is_file() and not path.name.endswith(".sha256")
            and not path.name.endswith("-standalone-release-metadata.json")
        )
        if not artifact_paths:
            raise SystemExit(f"No release artifacts found in {output_dir}")
        records = []
        for artifact_path in artifact_paths:
            artifact_version, target = parse_artifact_filename(artifact_path.name)
            if artifact_version != version:
                raise SystemExit(
                    f"Artifact version mismatch: {artifact_path.name} != {version}",
                )
            records.append(artifact_record(artifact_path, version=version, target=target))
        write_sha256sums(output_dir, artifact_paths)
        metadata_path = write_release_metadata(
            output_dir=output_dir,
            version=version,
            artifacts=records,
        )
        print(f"Wrote merged metadata: {metadata_path}")
        return 0

    if args.os_name and args.arch:
        target = ReleaseTarget(args.os_name, args.arch)
    else:
        target = detect_release_target()

    artifact_path = prepare_release_artifact(
        built_executable=built_executable,
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
    print(f"Prepared release artifact: {artifact_path}")
    print(f"Wrote checksum: {checksum_path}")
    print(f"Wrote metadata: {metadata_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
