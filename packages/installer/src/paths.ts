import os from "node:os";
import path from "node:path";

/** Directory name for the npm-managed virtual environment under {@link resolveHmArchHome}. */
export const MANAGED_ENV_DIR_NAME = "python-env";

/**
 * Root directory for HM-Arch installer state (managed venv, metadata).
 * Override with ``HM_ARCH_HOME`` for tests or custom layouts.
 */
export function resolveHmArchHome(overrides?: { home?: string; envHome?: string | undefined }): string {
  const fromEnv = overrides?.envHome ?? process.env.HM_ARCH_HOME;
  if (fromEnv) {
    return path.resolve(fromEnv);
  }
  if (overrides?.home) {
    return path.join(overrides.home, ".hm-arch");
  }
  if (process.platform === "win32") {
    const base = process.env.LOCALAPPDATA ?? path.join(os.homedir(), "AppData", "Local");
    return path.join(base, "hm-arch");
  }
  return path.join(os.homedir(), ".hm-arch");
}

export function managedEnvRoot(hmArchHome: string): string {
  return path.join(hmArchHome, MANAGED_ENV_DIR_NAME);
}

export function managedEnvStatePath(hmArchHome: string): string {
  return path.join(managedEnvRoot(hmArchHome), "state.json");
}

/** ``bin/python`` on Unix; ``Scripts\\python.exe`` on Windows. */
export function managedPythonExecutable(hmArchHome: string): string {
  const root = managedEnvRoot(hmArchHome);
  if (process.platform === "win32") {
    return path.join(root, "Scripts", "python.exe");
  }
  return path.join(root, "bin", "python");
}

export function managedPipExecutable(hmArchHome: string): string {
  const root = managedEnvRoot(hmArchHome);
  if (process.platform === "win32") {
    return path.join(root, "Scripts", "pip.exe");
  }
  return path.join(root, "bin", "pip");
}
