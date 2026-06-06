import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";

import { BUNDLED_HM_ARCH_VERSION } from "../src/bundled-version.js";
import {
  describeManagedEnv,
  ensureManagedPythonEnv,
  readManagedEnvState,
  resolvePipSpec,
  writeManagedEnvState,
} from "../src/python-env.js";
import { managedPythonExecutable } from "../src/paths.js";
import {
  hasSupportedPython,
  withExclusiveEditablePipInstall,
  withSupportedPythonEnv,
} from "./test-helpers.js";

const REPO_ROOT = join(import.meta.dirname, "..", "..", "..");

function tempHome(): string {
  return mkdtempSync(join(tmpdir(), "hm-arch-installer-"));
}

function editablePipSpec(): string {
  return REPO_ROOT;
}

describe("python-env (unit)", () => {
  it("defaults pip spec to bundled hm-arch version", () => {
    assert.equal(resolvePipSpec(), `hm-arch==${BUNDLED_HM_ARCH_VERSION}`);
    assert.equal(resolvePipSpec({ pipSpec: "hm-arch==9.9.9" }), "hm-arch==9.9.9");
  });

  it("creates venv and installs via managed pip only", () => {
    const home = tempHome();
    const calls: Array<{ file: string; args: string[] }> = [];
    let venvReady = false;
    try {
      const result = ensureManagedPythonEnv(
        {},
        {
          hmArchHome: home,
          pipSpec: `hm-arch==${BUNDLED_HM_ARCH_VERSION}`,
          probe: () => ({
            executable: "python3",
            version: "3.12.0",
            major: 3,
            minor: 12,
          }),
          runCommand: (file, args) => {
            calls.push({ file, args });
            if (args.includes("venv")) {
              venvReady = true;
            }
            if (args.some((arg) => arg.includes("import hm_arch"))) {
              return BUNDLED_HM_ARCH_VERSION;
            }
            return "";
          },
          exists: (path) => {
            if (path === managedPythonExecutable(home)) {
              return venvReady;
            }
            return false;
          },
          mkdir: () => undefined,
          writeState: (root, state) => writeManagedEnvState(root, state),
        },
      );
      assert.equal(result.action, "created");
      assert.ok(calls.some((call) => call.args.includes("venv")));
      const pipCalls = calls.filter((call) => call.args[0] === "install");
      assert.equal(pipCalls.length, 1);
      assert.deepEqual(pipCalls[0]?.args.slice(0, 2), ["install", "--disable-pip-version-check"]);
      const state = readManagedEnvState(home);
      assert.equal(state?.hmArchVersion, BUNDLED_HM_ARCH_VERSION);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("reuses an existing compatible environment", () => {
    const home = tempHome();
    let installCount = 0;
    let venvReady = false;
    const sharedDeps = {
      hmArchHome: home,
      pipSpec: `hm-arch==${BUNDLED_HM_ARCH_VERSION}`,
      probe: () => ({
        executable: "python3",
        version: "3.12.0",
        major: 3,
        minor: 12,
      }),
      runCommand: (file: string, args: string[]) => {
        if (args.includes("venv")) {
          venvReady = true;
        }
        if (args[0] === "install") {
          installCount += 1;
        }
        if (args.some((arg) => arg.includes("import hm_arch"))) {
          return BUNDLED_HM_ARCH_VERSION;
        }
        return "";
      },
      exists: (path: string) => {
        if (path.endsWith("state.json")) {
          return venvReady;
        }
        return path === managedPythonExecutable(home) && venvReady;
      },
      mkdir: () => undefined,
      writeState: (root: string, state: Parameters<typeof writeManagedEnvState>[1]) =>
        writeManagedEnvState(root, state),
    };
    try {
      ensureManagedPythonEnv({}, sharedDeps);
      const second = ensureManagedPythonEnv({}, sharedDeps);
      assert.equal(second.action, "reused");
      assert.equal(installCount, 1);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("upgrades when target version changes", () => {
    const home = tempHome();
    let installedVersion = "1.0.0";
    let installCount = 0;
    let venvReady = false;
    const baseDeps = {
      hmArchHome: home,
      probe: () => ({
        executable: "python3",
        version: "3.12.0",
        major: 3,
        minor: 12,
      }),
      runCommand: (file: string, args: string[]) => {
        if (args.includes("venv")) {
          venvReady = true;
        }
        if (args[0] === "install") {
          installCount += 1;
          if (args.includes("--upgrade")) {
            installedVersion = "1.0.1";
          }
        }
        if (args.some((arg) => arg.includes("import hm_arch"))) {
          return installedVersion;
        }
        return "";
      },
      exists: (path: string) => {
        if (path.endsWith("state.json")) {
          return venvReady;
        }
        return path === managedPythonExecutable(home) && venvReady;
      },
      mkdir: () => undefined,
      writeState: (root: string, state: Parameters<typeof writeManagedEnvState>[1]) =>
        writeManagedEnvState(root, state),
    };
    try {
      ensureManagedPythonEnv({}, { ...baseDeps, pipSpec: "hm-arch==1.0.0", targetVersion: "1.0.0" });
      const upgraded = ensureManagedPythonEnv(
        { upgrade: true },
        { ...baseDeps, pipSpec: "hm-arch==1.0.1", targetVersion: "1.0.1" },
      );
      assert.equal(upgraded.action, "upgraded");
      assert.ok(installCount >= 2);
      assert.equal(readManagedEnvState(home)?.hmArchVersion, "1.0.1");
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("describeManagedEnv reports missing install", () => {
    const home = tempHome();
    try {
      const status = describeManagedEnv({
        hmArchHome: home,
        exists: () => false,
      });
      assert.equal(status.hmArchImportable, false);
      assert.equal(status.state, null);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });
});

describe("python-env (integration)", { skip: !hasSupportedPython() }, () => {
  it("installs hm-arch editable without mutating global site-packages", async () => {
    await withExclusiveEditablePipInstall(() =>
      withSupportedPythonEnv(() => {
      const home = tempHome();
      const pythonExecutable = process.env.HM_ARCH_PYTHON;
      assert.ok(pythonExecutable);
      const globalSnapshot = execJson(pythonExecutable, [
        "-m",
        "pip",
        "list",
        "--format=json",
      ]);
      try {
        const result = ensureManagedPythonEnv(
          {},
          {
            hmArchHome: home,
            pipSpec: editablePipSpec(),
          },
        );
        assert.ok(["created", "upgraded", "reused"].includes(result.action));
        const second = ensureManagedPythonEnv({}, { hmArchHome: home, pipSpec: editablePipSpec() });
        assert.equal(second.action, "reused");

        const upgraded = ensureManagedPythonEnv(
          { upgrade: true },
          { hmArchHome: home, pipSpec: editablePipSpec() },
        );
        assert.ok(["reused", "upgraded"].includes(upgraded.action));

        const status = describeManagedEnv({ hmArchHome: home });
        assert.equal(status.hmArchImportable, true);
        assert.equal(status.installedHmArchVersion, BUNDLED_HM_ARCH_VERSION);

        const globalAfter = execJson(pythonExecutable, [
          "-m",
          "pip",
          "list",
          "--format=json",
        ]);
        assert.deepEqual(globalSnapshot, globalAfter);
      } finally {
        rmSync(home, { recursive: true, force: true });
      }
      }),
    );
  });
});

describe("python-env install failure", () => {
  it("surfaces pip errors from ensureManagedPythonEnv", () => {
    const home = tempHome();
    let venvReady = false;
    try {
      assert.throws(
        () =>
          ensureManagedPythonEnv(
            {},
            {
              hmArchHome: home,
              pipSpec: "hm-arch-not-a-real-package-xyz",
              probe: () => ({
                executable: "python3",
                version: "3.12.0",
                major: 3,
                minor: 12,
              }),
              runCommand: (file, args) => {
                if (args.includes("venv")) {
                  venvReady = true;
                  return "";
                }
                if (args[0] === "install") {
                  throw new Error("pip install failed: package not found");
                }
                return "";
              },
              exists: (path) => path === managedPythonExecutable(home) && venvReady,
              mkdir: () => undefined,
            },
          ),
        /pip install failed/,
      );
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });
});

function execJson(executable: string, args: string[]): unknown {
  const output = execFileSync(executable, args, { encoding: "utf8" });
  return JSON.parse(output);
}
