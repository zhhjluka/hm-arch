import { execFileSync } from "node:child_process";
import os from "node:os";

import { ENV_HM_ARCH_RUNTIME, MIN_NODE_MAJOR, MIN_PYTHON, SUPPORTED_OS } from "./constants.js";
import { detectReleaseTarget, releaseTargetSupportDiagnostic } from "./release-target.js";

export type PlatformInfo = {
  os: NodeJS.Platform;
  arch: string;
  nodeVersion: string;
  nodeMajor: number;
  python: PythonProbe | null;
};

export type PythonProbe = {
  executable: string;
  version: string;
  major: number;
  minor: number;
};

export type EnvironmentDiagnostic = {
  level: "error" | "warning";
  code: string;
  message: string;
  hint?: string;
};

function parseNodeMajor(version: string): number {
  const match = /^v(\d+)/.exec(version);
  return match ? Number.parseInt(match[1], 10) : 0;
}

function parsePythonVersion(output: string): { version: string; major: number; minor: number } | null {
  const match = /Python\s+(\d+)\.(\d+)\.(\d+)/i.exec(output.trim());
  if (!match) {
    return null;
  }
  return {
    version: `${match[1]}.${match[2]}.${match[3]}`,
    major: Number.parseInt(match[1], 10),
    minor: Number.parseInt(match[2], 10),
  };
}

function compareVersion(major: number, minor: number, minimum: string): boolean {
  const [minMajor, minMinor] = minimum.split(".").map((part) => Number.parseInt(part, 10));
  if (major > minMajor) {
    return true;
  }
  if (major < minMajor) {
    return false;
  }
  return minor >= minMinor;
}

/**
 * Probe common Python executables without throwing.
 * ``overrides`` supports tests (inject a fake probe function).
 */
function defaultPythonExecutables(envPython: string | undefined): string[] {
  return (envPython ? [envPython] : []).concat([
    "python3.13",
    "python3.12",
    "python3.11",
    "python3.10",
    "python3",
    "python",
  ]);
}

export function probePython(
  overrides?: Partial<{
    executables: string[];
    run: (executable: string) => string;
    envPython: string | undefined;
  }>,
): PythonProbe | null {
  const envPython = overrides?.envPython ?? process.env.HM_ARCH_PYTHON;
  const executables =
    overrides?.executables ?? defaultPythonExecutables(envPython);
  const run =
    overrides?.run ??
    ((executable: string) =>
      execFileSync(executable, ["--version"], {
        encoding: "utf8",
        stdio: ["ignore", "pipe", "pipe"],
      }));

  for (const executable of executables) {
    try {
      const output = run(executable);
      const parsed = parsePythonVersion(output);
      if (parsed) {
        return { executable, ...parsed };
      }
    } catch {
      // try next candidate
    }
  }
  return null;
}

/**
 * Find a Python interpreter that satisfies ``MIN_PYTHON``.
 * Prefers ``HM_ARCH_PYTHON``, then version-suffixed binaries before generic ``python3``.
 */
export function probeSupportedPython(
  overrides?: Partial<{
    executables: string[];
    run: (executable: string) => string;
    envPython: string | undefined;
  }>,
): PythonProbe | null {
  const envPython = overrides?.envPython ?? process.env.HM_ARCH_PYTHON;
  const executables =
    overrides?.executables ?? defaultPythonExecutables(envPython);
  const run =
    overrides?.run ??
    ((executable: string) =>
      execFileSync(executable, ["--version"], {
        encoding: "utf8",
        stdio: ["ignore", "pipe", "pipe"],
      }));

  for (const executable of executables) {
    try {
      const output = run(executable);
      const parsed = parsePythonVersion(output);
      if (parsed && compareVersion(parsed.major, parsed.minor, MIN_PYTHON)) {
        return { executable, ...parsed };
      }
    } catch {
      // try next candidate
    }
  }
  return null;
}

export function detectPlatform(
  overrides?: Partial<{
    platform: NodeJS.Platform;
    arch: string;
    nodeVersion: string;
    python: PythonProbe | null;
  }>,
): PlatformInfo {
  const nodeVersion = overrides?.nodeVersion ?? process.version;
  return {
    os: overrides?.platform ?? process.platform,
    arch: overrides?.arch ?? process.arch,
    nodeVersion,
    nodeMajor: parseNodeMajor(nodeVersion),
    python: overrides?.python === undefined ? probePython() : overrides.python,
  };
}

/** Return actionable diagnostics for unsupported or incomplete environments. */
export function environmentDiagnostics(
  info: PlatformInfo = detectPlatform(),
): EnvironmentDiagnostic[] {
  const diagnostics: EnvironmentDiagnostic[] = [];

  if (!SUPPORTED_OS.has(info.os)) {
    diagnostics.push({
      level: "error",
      code: "unsupported_os",
      message: `Unsupported operating system: ${info.os}`,
      hint:
        "HM-Arch npm installer supports macOS (darwin), Linux, and Windows. " +
        "Use pip or pipx to install hm-arch on other platforms.",
    });
  }

  if (info.nodeMajor < MIN_NODE_MAJOR) {
    diagnostics.push({
      level: "error",
      code: "unsupported_node",
      message: `Node.js ${info.nodeVersion} is below the minimum (v${MIN_NODE_MAJOR}.x).`,
      hint: `Upgrade Node.js to v${MIN_NODE_MAJOR} or newer, then re-run hm-arch-install doctor.`,
    });
  }

  const runtimeMode = (process.env[ENV_HM_ARCH_RUNTIME] ?? "auto").toLowerCase();
  const standaloneAvailable =
    detectReleaseTarget({ platform: info.os, arch: info.arch }) !== null;
  const wantsStandalone =
    runtimeMode === "standalone" || (runtimeMode === "auto" && standaloneAvailable);
  const wantsPython =
    runtimeMode === "python" || (runtimeMode === "auto" && !standaloneAvailable);

  const releaseTargetDiagnostic = releaseTargetSupportDiagnostic(info.os, info.arch);
  if (releaseTargetDiagnostic) {
    const hasPython =
      info.python !== null &&
      compareVersion(info.python.major, info.python.minor, MIN_PYTHON);
    if (wantsStandalone || runtimeMode === "standalone" || !hasPython) {
      diagnostics.push({ ...releaseTargetDiagnostic, level: "error" });
    } else if (runtimeMode === "auto") {
      diagnostics.push({
        ...releaseTargetDiagnostic,
        level: "warning",
        code: "unsupported_release_target",
        message: `${releaseTargetDiagnostic.message} Standalone install unavailable; using Python runtime.`,
      });
    }
  }

  if (wantsPython) {
    if (!info.python) {
      diagnostics.push({
        level: "error",
        code: "python_missing",
        message: "Python 3 was not found on PATH.",
        hint:
          `Install Python ${MIN_PYTHON}+ and ensure python3 is on PATH, ` +
          "or set HM_ARCH_PYTHON to the interpreter path.",
      });
    } else if (!compareVersion(info.python.major, info.python.minor, MIN_PYTHON)) {
      diagnostics.push({
        level: "error",
        code: "unsupported_python",
        message: `Python ${info.python.version} is below the minimum (${MIN_PYTHON}).`,
        hint: `Upgrade to Python ${MIN_PYTHON}+ (found via ${info.python.executable}).`,
      });
    }
  } else if (!info.python && wantsStandalone) {
    diagnostics.push({
      level: "warning",
      code: "python_missing",
      message: "Python 3 was not found on PATH.",
      hint:
        "Standalone binaries are used on this platform; Python is optional unless you set HM_ARCH_RUNTIME=python.",
    });
  }

  const knownArm = new Set(["arm64", "aarch64"]);
  const knownX64 = new Set(["x64", "amd64"]);
  if (!knownArm.has(info.arch) && !knownX64.has(info.arch)) {
    diagnostics.push({
      level: "warning",
      code: "unknown_arch",
      message: `Untested CPU architecture: ${info.arch}`,
      hint: "Installation may still work; report issues if hm-arch-install fails on this platform.",
    });
  }

  return diagnostics;
}

export function hasBlockingDiagnostics(diagnostics: EnvironmentDiagnostic[]): boolean {
  return diagnostics.some((item) => item.level === "error");
}

export function formatDiagnostics(diagnostics: EnvironmentDiagnostic[]): string {
  if (diagnostics.length === 0) {
    return "Environment OK.";
  }
  return diagnostics
    .map((item) => {
      const prefix = item.level === "error" ? "error" : "warning";
      const hint = item.hint ? `\n  hint: ${item.hint}` : "";
      return `${prefix} [${item.code}]: ${item.message}${hint}`;
    })
    .join("\n");
}

export function platformSummary(info: PlatformInfo = detectPlatform()): string {
  const pythonLine = info.python
    ? `${info.python.executable} (${info.python.version})`
    : "not found";
  return [
    `os: ${info.os}`,
    `arch: ${info.arch}`,
    `node: ${info.nodeVersion}`,
    `python: ${pythonLine}`,
    `cpus: ${os.cpus().length}`,
  ].join("\n");
}
