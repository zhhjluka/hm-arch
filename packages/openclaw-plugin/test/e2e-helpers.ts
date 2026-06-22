import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { DEFAULT_PLUGIN_CONFIG, type PluginConfig } from "../src/config.js";

export const PACKAGE_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
export const REPO_ROOT = join(PACKAGE_ROOT, "..", "..");

export type E2EContext = {
  workdir: string;
  dbPath: string;
  sidecarCommand: string[];
  sidecarEnv: NodeJS.ProcessEnv;
  config: PluginConfig;
  cleanup: () => void;
};

function currentSourceEnv(): NodeJS.ProcessEnv {
  const sourceRoot = join(REPO_ROOT, "src");
  return {
    ...process.env,
    PYTHONPATH: [sourceRoot, process.env.PYTHONPATH].filter(Boolean).join(delimiter),
  };
}

function resolvePythonExecutable(env: NodeJS.ProcessEnv): string {
  const candidates = [
    process.env.HM_ARCH_PYTHON,
    process.env.PYTHON,
    "python3",
    "python",
  ];
  for (const candidate of candidates) {
    if (!candidate) {
      continue;
    }
    const probe = spawnSync(candidate, ["-c", "import hm_arch.integrations.openclaw.sidecar"], {
      encoding: "utf8",
      env,
    });
    if (probe.status === 0) {
      return candidate;
    }
  }
  throw new Error(
    "HM-Arch Python package is required for OpenClaw E2E tests. " +
      "Install with `python -m pip install -e .` or set HM_ARCH_PYTHON.",
  );
}

export function hasPythonSidecarSupport(): boolean {
  try {
    resolvePythonExecutable(currentSourceEnv());
    return true;
  } catch {
    return false;
  }
}

export function createE2EContext(overrides: Partial<PluginConfig> = {}): E2EContext {
  const sidecarEnv = currentSourceEnv();
  const python = resolvePythonExecutable(sidecarEnv);
  const workdir = mkdtempSync(join(tmpdir(), "hm-arch-openclaw-e2e-"));
  const dbPath = join(workdir, "hm_arch_memory.db");
  const config: PluginConfig = {
    ...DEFAULT_PLUGIN_CONFIG,
    dbPath,
    sidecarCommand: [python, "-m", "hm_arch.integrations.cli.main", "openclaw", "sidecar"],
    requestTimeoutMs: 15_000,
    startupTimeoutMs: 30_000,
    maxRestartBackoffMs: 5_000,
    ...overrides,
  };
  return {
    workdir,
    dbPath,
    sidecarCommand: config.sidecarCommand,
    sidecarEnv,
    config,
    cleanup: () => {
      rmSync(workdir, { recursive: true, force: true });
    },
  };
}
