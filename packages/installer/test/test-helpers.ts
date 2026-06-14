import { chmodSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { delimiter, join } from "node:path";

import { readBundledHmArchVersion } from "../src/bundled-version.js";
import { readInstallerVersion } from "../src/installer-version.js";
import { sha256Buffer } from "../src/integrity.js";
import {
  managedStandaloneExecutable,
  standaloneBinaryRoot,
} from "../src/paths.js";
import { probeSupportedPython } from "../src/platform.js";
import { detectReleaseTarget, releaseArtifactFilename } from "../src/release-target.js";
import {
  writeStandaloneBinaryState,
  type StandaloneBinaryState,
} from "../src/standalone-binary.js";

const REPO_ROOT = join(import.meta.dirname, "..", "..", "..");

/** Invoke npm with a Windows-compatible executable (npm.cmd + shell). */
export function execNpmSync(
  args: string[],
  options?: Parameters<typeof execFileSync>[2],
): Buffer | string {
  if (process.platform === "win32") {
    return execFileSync("npm.cmd", args, { ...options, shell: true });
  }
  return execFileSync("npm", args, options);
}

/** Path to a package binary under node_modules/.bin (includes .cmd on Windows). */
export function localPackageBin(projectDir: string, name: string): string {
  const binDir = join(projectDir, "node_modules", ".bin");
  return process.platform === "win32" ? join(binDir, `${name}.cmd`) : join(binDir, name);
}

/** True when a Python >= MIN_PYTHON interpreter is available for integration tests. */
export function hasSupportedPython(): boolean {
  return probeSupportedPython() !== null;
}

const EDITABLE_PIP_LOCK_DIR = join(
  tmpdir(),
  `hm-arch-editable-pip-${Buffer.from(REPO_ROOT).toString("hex")}.lock`,
);
const EDITABLE_PIP_LOCK_STALE_MS = 5 * 60 * 1000;
const EDITABLE_PIP_LOCK_POLL_MS = 100;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function withExclusiveEditablePipInstall<T>(
  fn: () => T | Promise<T>,
): Promise<T> {
  while (true) {
    try {
      mkdirSync(EDITABLE_PIP_LOCK_DIR);
      break;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") {
        throw error;
      }
      try {
        const lockAge = Date.now() - statSync(EDITABLE_PIP_LOCK_DIR).mtimeMs;
        if (lockAge > EDITABLE_PIP_LOCK_STALE_MS) {
          rmSync(EDITABLE_PIP_LOCK_DIR, { recursive: true, force: true });
          continue;
        }
      } catch {
        // The lock disappeared between mkdir and stat; retry immediately.
        continue;
      }
      await sleep(EDITABLE_PIP_LOCK_POLL_MS);
    }
  }

  try {
    return await fn();
  } finally {
    rmSync(EDITABLE_PIP_LOCK_DIR, { recursive: true, force: true });
  }
}

/** Apply HM_ARCH_PYTHON for tests when a supported interpreter is available. */
export async function withSupportedPythonEnv<T>(fn: () => T | Promise<T>): Promise<T> {
  const python = probeSupportedPython();
  if (!python) {
    throw new Error("supported Python interpreter required");
  }
  const previous = process.env.HM_ARCH_PYTHON;
  process.env.HM_ARCH_PYTHON = python.executable;
  try {
    return await fn();
  } finally {
    if (previous === undefined) {
      delete process.env.HM_ARCH_PYTHON;
    } else {
      process.env.HM_ARCH_PYTHON = previous;
    }
  }
}

/** Remove Python executables from PATH for clean-machine verification. */
export function stripPythonFromPath(): { restore: () => void } {
  const previousPath = process.env.PATH;
  const previousHmArchPython = process.env.HM_ARCH_PYTHON;
  const filtered = (previousPath ?? "")
    .split(delimiter)
    .filter((entry) => !/(^|[\\/])python(\d+(\.\d+)?)?(\.exe)?$/i.test(entry.trim()))
    .join(delimiter);
  process.env.PATH = filtered;
  delete process.env.HM_ARCH_PYTHON;
  return {
    restore: () => {
      if (previousPath === undefined) {
        delete process.env.PATH;
      } else {
        process.env.PATH = previousPath;
      }
      if (previousHmArchPython === undefined) {
        delete process.env.HM_ARCH_PYTHON;
      } else {
        process.env.HM_ARCH_PYTHON = previousHmArchPython;
      }
    },
  };
}

/** Resolve a built standalone hm-arch executable for integration tests. */
export function resolveStandaloneFixtureBinary(): string | null {
  const fromEnv = process.env.HM_ARCH_STANDALONE_FIXTURE;
  if (fromEnv && existsSync(fromEnv)) {
    return fromEnv;
  }
  const defaultName = process.platform === "win32" ? "hm-arch.exe" : "hm-arch";
  const defaultPath = join(REPO_ROOT, "dist", "standalone", defaultName);
  if (existsSync(defaultPath)) {
    return defaultPath;
  }
  return null;
}

/** True when a real standalone hm-arch binary is available for E2E tests. */
export function hasStandaloneFixture(): boolean {
  return resolveStandaloneFixtureBinary() !== null;
}

/** Install a fixture standalone binary directly under HM_ARCH_HOME (no network). */
export function installStandaloneFixtureBinary(
  hmArchHome: string,
  fixturePath: string = resolveStandaloneFixtureBinary() ?? "",
): StandaloneBinaryState {
  if (!fixturePath || !existsSync(fixturePath)) {
    throw new Error("standalone fixture binary not found");
  }
  const target = detectReleaseTarget();
  if (!target) {
    throw new Error("unsupported release target for standalone fixture install");
  }
  const version = readBundledHmArchVersion();
  const filename = releaseArtifactFilename(version, target);
  const bytes = readFileSync(fixturePath);
  const root = standaloneBinaryRoot(hmArchHome);
  mkdirSync(root, { recursive: true });
  const executable = managedStandaloneExecutable(hmArchHome);
  copyFileSync(fixturePath, executable);
  if (process.platform !== "win32") {
    chmodSync(executable, 0o755);
  }
  const now = new Date().toISOString();
  const state: StandaloneBinaryState = {
    hmArchVersion: version,
    targetOs: target.os,
    targetArch: target.arch,
    filename,
    sha256: sha256Buffer(bytes),
    sizeBytes: bytes.length,
    installerVersion: readInstallerVersion(),
    createdAt: now,
    updatedAt: now,
  };
  writeStandaloneBinaryState(hmArchHome, state);
  return state;
}

/** Run a callback with HM_ARCH_HOME and standalone runtime, optionally without Python on PATH. */
export async function withStandaloneRuntimeEnv<T>(
  options: {
    stripPython?: boolean;
    installFixture?: boolean;
  },
  fn: (ctx: { home: string; workdir: string }) => T | Promise<T>,
): Promise<T> {
  const home = mkdtempSync(join(tmpdir(), "hm-arch-clean-"));
  const workdir = mkdtempSync(join(tmpdir(), "hm-arch-project-"));
  mkdirSync(workdir, { recursive: true });

  const previousHome = process.env.HM_ARCH_HOME;
  const previousHermesHome = process.env.HERMES_HOME;
  const previousRuntime = process.env.HM_ARCH_RUNTIME;
  const previousCwd = process.cwd();
  const pathGuard = options.stripPython ? stripPythonFromPath() : null;

  process.env.HM_ARCH_HOME = home;
  process.env.HERMES_HOME = join(home, "hermes-home");
  process.env.HM_ARCH_RUNTIME = "standalone";
  process.chdir(workdir);

  try {
    if (options.installFixture !== false) {
      installStandaloneFixtureBinary(home);
    }
    return await fn({ home, workdir });
  } finally {
    process.chdir(previousCwd);
    if (previousHome === undefined) {
      delete process.env.HM_ARCH_HOME;
    } else {
      process.env.HM_ARCH_HOME = previousHome;
    }
    if (previousHermesHome === undefined) {
      delete process.env.HERMES_HOME;
    } else {
      process.env.HERMES_HOME = previousHermesHome;
    }
    if (previousRuntime === undefined) {
      delete process.env.HM_ARCH_RUNTIME;
    } else {
      process.env.HM_ARCH_RUNTIME = previousRuntime;
    }
    pathGuard?.restore();
    rmSync(home, { recursive: true, force: true });
    rmSync(workdir, { recursive: true, force: true });
  }
}
