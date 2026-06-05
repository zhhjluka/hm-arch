import type { EnvironmentDiagnostic } from "./platform.js";

/** Supported standalone release triple (MEM-62). */
export type ReleaseOs = "linux" | "darwin" | "windows";
export type ReleaseArch = "x86_64" | "aarch64" | "arm64";

export type ReleaseTarget = {
  os: ReleaseOs;
  arch: ReleaseArch;
};

export const SUPPORTED_RELEASE_TARGETS: readonly ReleaseTarget[] = [
  { os: "linux", arch: "x86_64" },
  { os: "linux", arch: "aarch64" },
  { os: "darwin", arch: "arm64" },
  { os: "windows", arch: "x86_64" },
] as const;

const SUPPORTED_SUFFIXES = new Set(
  SUPPORTED_RELEASE_TARGETS.map((target) => `${target.os}-${target.arch}`),
);

export function artifactSuffix(target: ReleaseTarget): string {
  return `${target.os}-${target.arch}`;
}

export function isSupportedReleaseTarget(target: ReleaseTarget): boolean {
  return SUPPORTED_SUFFIXES.has(artifactSuffix(target));
}

/** Map Node ``process.arch`` to release artifact arch naming. */
export function normalizeNodeArch(
  arch: string,
  os: NodeJS.Platform,
): ReleaseArch | null {
  const lowered = arch.toLowerCase();
  if (lowered === "x64" || lowered === "x86_64" || lowered === "amd64") {
    return "x86_64";
  }
  if (lowered === "arm64") {
    return os === "darwin" ? "arm64" : "aarch64";
  }
  if (lowered === "aarch64") {
    return "aarch64";
  }
  return null;
}

/** Map Node ``process.platform`` to release OS naming. */
export function normalizeNodeOs(platform: NodeJS.Platform): ReleaseOs | null {
  if (platform === "linux") {
    return "linux";
  }
  if (platform === "darwin") {
    return "darwin";
  }
  if (platform === "win32") {
    return "windows";
  }
  return null;
}

export function detectReleaseTarget(
  overrides?: Partial<{ platform: NodeJS.Platform; arch: string }>,
): ReleaseTarget | null {
  const platform = overrides?.platform ?? process.platform;
  const arch = overrides?.arch ?? process.arch;
  const os = normalizeNodeOs(platform);
  const releaseArch = normalizeNodeArch(arch, platform);
  if (!os || !releaseArch) {
    return null;
  }
  const target: ReleaseTarget = { os, arch: releaseArch };
  return isSupportedReleaseTarget(target) ? target : null;
}

export function releaseArtifactFilename(version: string, target: ReleaseTarget): string {
  const base = `hm-arch-${version}-${artifactSuffix(target)}`;
  return target.os === "windows" ? `${base}.exe` : base;
}

export function listSupportedTargetSummaries(): string {
  return SUPPORTED_RELEASE_TARGETS.map((target) => artifactSuffix(target)).join(", ");
}

export function releaseTargetSupportDiagnostic(
  platform: NodeJS.Platform = process.platform,
  arch: string = process.arch,
): EnvironmentDiagnostic | null {
  if (detectReleaseTarget({ platform, arch })) {
    return null;
  }
  if (!normalizeNodeOs(platform)) {
    return null;
  }
  return unsupportedReleaseTargetDiagnostic(platform, arch);
}

export function unsupportedReleaseTargetDiagnostic(
  platform: NodeJS.Platform = process.platform,
  arch: string = process.arch,
): EnvironmentDiagnostic {
  const os = normalizeNodeOs(platform);
  const releaseArch = normalizeNodeArch(arch, platform);
  const attempted =
    os && releaseArch ? artifactSuffix({ os, arch: releaseArch }) : `${platform}/${arch}`;

  let hint =
    `Supported standalone targets: ${listSupportedTargetSummaries()}. ` +
    "Install Python 3.10+ and use the managed pip workflow, or run on a supported platform.";

  if (platform === "darwin" && (arch === "x64" || arch === "x86_64")) {
    hint =
      "Intel Mac (darwin/x64) is not supported for standalone binaries. " +
      "Use an Apple Silicon Mac (darwin/arm64), Linux, or Windows x64, " +
      "or install Python 3.10+ for the pip-based installer path.";
  } else if (platform === "win32" && arch === "arm64") {
    hint =
      "Windows ARM64 is not supported for standalone binaries. " +
      "Use Windows x64, Linux, or macOS arm64, or install Python 3.10+ for the pip path.";
  }

  return {
    level: "error",
    code: "unsupported_release_target",
    message: `No standalone HM-Arch binary for ${attempted}.`,
    hint,
  };
}
