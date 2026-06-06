import { execFileSync, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";

import { BUNDLED_HM_ARCH_VERSION } from "./bundled-version.js";
import { INSTALLER_VERSION } from "./installer-version.js";
import type { PythonProbe } from "./platform.js";
import { probeSupportedPython } from "./platform.js";
import {
  managedEnvRoot,
  managedEnvStatePath,
  managedPipExecutable,
  managedPythonExecutable,
  resolveHmArchHome,
} from "./paths.js";

export type ManagedEnvState = {
  hmArchVersion: string;
  pythonVersion: string;
  pythonExecutable: string;
  installerVersion: string;
  createdAt: string;
  updatedAt: string;
};

export type ManagedEnvStatus = {
  home: string;
  root: string;
  python: string;
  pip: string;
  state: ManagedEnvState | null;
  hmArchImportable: boolean;
  installedHmArchVersion: string | null;
};

export type EnsureManagedEnvResult = {
  home: string;
  root: string;
  python: string;
  state: ManagedEnvState;
  action: "created" | "reused" | "upgraded";
};

export type PythonEnvDeps = {
  hmArchHome?: string;
  targetVersion?: string;
  /** pip requirement, e.g. ``hm-arch==2.0.0`` or an editable path for tests. */
  pipSpec?: string;
  probe?: () => PythonProbe | null;
  now?: () => string;
  exists?: (path: string) => boolean;
  mkdir?: (path: string) => void;
  readState?: (home: string) => ManagedEnvState | null;
  writeState?: (home: string, state: ManagedEnvState) => void;
  runCommand?: (file: string, args: string[], options?: { cwd?: string }) => string;
  readInstalledVersion?: (python: string) => string | null;
};

function defaultNow(): string {
  return new Date().toISOString();
}

function defaultExists(path: string): boolean {
  return existsSync(path);
}

function defaultMkdir(path: string): void {
  mkdirSync(path, { recursive: true });
}

function defaultRunCommand(file: string, args: string[], options?: { cwd?: string }): string {
  return execFileSync(file, args, {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    cwd: options?.cwd,
  }).trim();
}

export function readManagedEnvState(
  hmArchHome: string,
  deps: Pick<PythonEnvDeps, "exists" | "readState"> = {},
): ManagedEnvState | null {
  if (deps.readState) {
    return deps.readState(hmArchHome);
  }
  const exists = deps.exists ?? defaultExists;
  const statePath = managedEnvStatePath(hmArchHome);
  if (!exists(statePath)) {
    return null;
  }
  try {
    return JSON.parse(readFileSync(statePath, "utf8")) as ManagedEnvState;
  } catch {
    return null;
  }
}

export function writeManagedEnvState(
  hmArchHome: string,
  state: ManagedEnvState,
  deps: Pick<PythonEnvDeps, "mkdir" | "writeState"> = {},
): void {
  if (deps.writeState) {
    deps.writeState(hmArchHome, state);
    return;
  }
  const mkdir = deps.mkdir ?? defaultMkdir;
  const statePath = managedEnvStatePath(hmArchHome);
  mkdir(managedEnvRoot(hmArchHome));
  writeFileSync(statePath, `${JSON.stringify(state, null, 2)}\n`, "utf8");
}

export function resolvePipSpec(deps: PythonEnvDeps = {}): string {
  const fromEnv = process.env.HM_ARCH_PIP_SPEC;
  if (deps.pipSpec) {
    return deps.pipSpec;
  }
  if (fromEnv) {
    return fromEnv;
  }
  const version = deps.targetVersion ?? BUNDLED_HM_ARCH_VERSION;
  return `hm-arch==${version}`;
}

function managedVenvReady(hmArchHome: string, exists: (path: string) => boolean): boolean {
  return exists(managedPythonExecutable(hmArchHome));
}

export function readInstalledHmArchVersion(
  pythonExecutable: string,
  deps: Pick<PythonEnvDeps, "runCommand" | "readInstalledVersion"> = {},
): string | null {
  if (deps.readInstalledVersion) {
    return deps.readInstalledVersion(pythonExecutable);
  }
  const runCommand = deps.runCommand ?? defaultRunCommand;
  try {
    const output = runCommand(pythonExecutable, [
      "-c",
      "import hm_arch; print(hm_arch.__version__)",
    ]);
    const line = output.split("\n").pop()?.trim();
    return line || null;
  } catch {
    return null;
  }
}

export function describeManagedEnv(deps: PythonEnvDeps = {}): ManagedEnvStatus {
  const home = deps.hmArchHome ?? resolveHmArchHome();
  const exists = deps.exists ?? defaultExists;
  const python = managedPythonExecutable(home);
  const pip = managedPipExecutable(home);
  const state = readManagedEnvState(home, deps);
  const hmArchImportable = exists(python) && readInstalledHmArchVersion(python, deps) !== null;
  const installedHmArchVersion = hmArchImportable
    ? readInstalledHmArchVersion(python, deps)
    : null;
  return {
    home,
    root: managedEnvRoot(home),
    python,
    pip,
    state,
    hmArchImportable,
    installedHmArchVersion,
  };
}

function createManagedVenv(
  hmArchHome: string,
  python: PythonProbe,
  deps: PythonEnvDeps,
): void {
  const mkdir = deps.mkdir ?? defaultMkdir;
  const runCommand = deps.runCommand ?? defaultRunCommand;
  const root = managedEnvRoot(hmArchHome);
  mkdir(hmArchHome);
  runCommand(python.executable, ["-m", "venv", root]);
}

function installIntoManagedVenv(
  hmArchHome: string,
  pipSpec: string,
  upgrade: boolean,
  deps: PythonEnvDeps,
): void {
  const runCommand = deps.runCommand ?? defaultRunCommand;
  const pip = managedPipExecutable(hmArchHome);
  const args = ["install", "--disable-pip-version-check"];
  if (upgrade) {
    args.push("--upgrade");
  }
  args.push(pipSpec);
  runCommand(pip, args);
}

function buildState(
  python: PythonProbe,
  hmArchVersion: string,
  previous: ManagedEnvState | null,
  now: string,
): ManagedEnvState {
  return {
    hmArchVersion,
    pythonVersion: python.version,
    pythonExecutable: python.executable,
    installerVersion: INSTALLER_VERSION,
    createdAt: previous?.createdAt ?? now,
    updatedAt: now,
  };
}

/**
 * Create or refresh the npm-managed Python environment and install ``hm-arch``.
 * Never invokes the system/global ``pip`` except via ``python -m venv``.
 */
export function ensureManagedPythonEnv(
  options: { forceRecreate?: boolean; upgrade?: boolean } = {},
  deps: PythonEnvDeps = {},
): EnsureManagedEnvResult {
  const exists = deps.exists ?? defaultExists;
  const now = (deps.now ?? defaultNow)();
  const home = deps.hmArchHome ?? resolveHmArchHome();
  const python = (deps.probe ?? probeSupportedPython)();
  if (!python) {
    throw new Error("python_missing");
  }

  const targetVersion = deps.targetVersion ?? BUNDLED_HM_ARCH_VERSION;
  const pipSpec = resolvePipSpec({ ...deps, targetVersion });
  const previous = readManagedEnvState(home, deps);
  const venvReady = managedVenvReady(home, exists);

  let action: EnsureManagedEnvResult["action"];

  if (!venvReady || options.forceRecreate) {
    createManagedVenv(home, python, deps);
    installIntoManagedVenv(home, pipSpec, false, deps);
    action = "created";
  } else {
    const installed = readInstalledHmArchVersion(managedPythonExecutable(home), deps);
    const needsUpgrade =
      options.upgrade === true ||
      installed === null ||
      installed !== targetVersion ||
      (previous !== null && previous.hmArchVersion !== targetVersion);

    if (needsUpgrade) {
      installIntoManagedVenv(home, pipSpec, true, deps);
      action = "upgraded";
    } else {
      action = "reused";
    }
  }

  const installedVersion =
    readInstalledHmArchVersion(managedPythonExecutable(home), deps) ?? targetVersion;
  const state = buildState(python, installedVersion, previous, now);
  writeManagedEnvState(home, state, deps);

  return {
    home,
    root: managedEnvRoot(home),
    python: managedPythonExecutable(home),
    state,
    action,
  };
}

/** Run a subprocess using only the managed interpreter (for tests). */
export function runManagedPython(
  hmArchHome: string,
  args: string[],
  deps: Pick<PythonEnvDeps, "exists"> = {},
): { status: number; stdout: string; stderr: string } {
  const exists = deps.exists ?? defaultExists;
  const python = managedPythonExecutable(hmArchHome);
  if (!exists(python)) {
    throw new Error("managed_python_missing");
  }
  const result = spawnSync(python, args, { encoding: "utf8" });
  return {
    status: result.status ?? 1,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
  };
}

export function formatManagedEnvSummary(status: ManagedEnvStatus): string {
  const lines = [
    `hm-arch home: ${status.home}`,
    `managed venv: ${status.root}`,
    `managed python: ${status.python}`,
  ];
  if (status.state) {
    lines.push(`hm-arch (state): ${status.state.hmArchVersion}`);
    lines.push(`python (state): ${status.state.pythonVersion}`);
  }
  if (status.installedHmArchVersion) {
    lines.push(`hm-arch (import): ${status.installedHmArchVersion}`);
  } else {
    lines.push("hm-arch (import): not installed");
  }
  return lines.join("\n");
}

export function formatEnsureResult(result: EnsureManagedEnvResult): string {
  const verb =
    result.action === "created"
      ? "Created"
      : result.action === "upgraded"
        ? "Upgraded"
        : "Reused";
  return [
    `${verb} npm-managed Python environment.`,
    `  home: ${result.home}`,
    `  venv: ${result.root}`,
    `  python: ${result.python}`,
    `  hm-arch: ${result.state.hmArchVersion}`,
  ].join("\n");
}
