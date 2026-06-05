import { execFileSync } from "node:child_process";
import { join } from "node:path";

import { probeSupportedPython } from "../src/platform.js";

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

/**
 * Serialize editable ``pip install`` runs against the repo checkout.
 * Node's test runner executes files in parallel; concurrent wheel builds in the
 * same source tree race and flake on CI (macOS/Windows).
 */
let editablePipInstallChain: Promise<unknown> = Promise.resolve();

export async function withExclusiveEditablePipInstall<T>(
  fn: () => T | Promise<T>,
): Promise<T> {
  const waitFor = editablePipInstallChain;
  let release!: () => void;
  editablePipInstallChain = new Promise<void>((resolve) => {
    release = resolve;
  });
  await waitFor;
  try {
    return await fn();
  } finally {
    release();
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
