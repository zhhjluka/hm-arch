"""Naming helpers for cross-platform standalone release artifacts (MEM-62)."""

from __future__ import annotations

import platform
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ReleaseTarget:
    """A supported standalone release platform triple."""

    os_name: str
    arch: str

    def artifact_suffix(self) -> str:
        return f"{self.os_name}-{self.arch}"

    def filename(self, version: str) -> str:
        base = f"hm-arch-{version}-{self.artifact_suffix()}"
        if self.os_name == "windows":
            return f"{base}.exe"
        return base


_SUPPORTED_TARGETS: tuple[ReleaseTarget, ...] = (
    ReleaseTarget("linux", "x86_64"),
    ReleaseTarget("linux", "aarch64"),
    ReleaseTarget("darwin", "x86_64"),
    ReleaseTarget("darwin", "arm64"),
    ReleaseTarget("windows", "x86_64"),
)


def supported_release_targets() -> tuple[ReleaseTarget, ...]:
    return _SUPPORTED_TARGETS


def normalize_arch(machine: str, *, os_name: str | None = None) -> str:
    lowered = machine.lower()
    if lowered in {"x86_64", "amd64", "x64"}:
        return "x86_64"
    if lowered in {"aarch64", "arm64"}:
        effective_os = os_name or normalize_os(platform.system())
        return "arm64" if effective_os == "darwin" else "aarch64"
    raise ValueError(f"Unsupported CPU architecture for release artifacts: {machine}")


def normalize_os(system: str) -> str:
    mapping = {
        "Linux": "linux",
        "Darwin": "darwin",
        "Windows": "windows",
    }
    try:
        return mapping[system]
    except KeyError as exc:
        raise ValueError(f"Unsupported operating system for release artifacts: {system}") from exc


def detect_release_target() -> ReleaseTarget:
    """Infer the release target for the current machine."""
    os_name = normalize_os(platform.system())
    return ReleaseTarget(
        os_name=os_name,
        arch=normalize_arch(platform.machine(), os_name=os_name),
    )


def parse_artifact_filename(filename: str) -> tuple[str, ReleaseTarget]:
    """Parse ``hm-arch-{version}-{os}-{arch}[.exe]`` into version and target."""
    match = re.fullmatch(
        r"hm-arch-(?P<version>\d+\.\d+\.\d+)-(?P<os>linux|darwin|windows)-(?P<arch>x86_64|aarch64|arm64)(?:\.exe)?",
        filename,
    )
    if not match:
        raise ValueError(f"Not a release artifact filename: {filename}")
    return match.group("version"), ReleaseTarget(match.group("os"), match.group("arch"))


def is_supported_target(target: ReleaseTarget) -> bool:
    return target in _SUPPORTED_TARGETS
