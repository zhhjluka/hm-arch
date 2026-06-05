import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";

function withTempWorkdir<T>(fn: (workdir: string) => T | Promise<T>): T | Promise<T> {
  const workdir = mkdtempSync(join(tmpdir(), "hm-arch-cmd-cwd-"));
  const previous = process.cwd();
  process.chdir(workdir);
  try {
    return fn(workdir);
  } finally {
    process.chdir(previous);
    rmSync(workdir, { recursive: true, force: true });
  }
}

import { runParsedCommand } from "../src/commands.js";
import {
  hasSupportedPython,
  withExclusiveEditablePipInstall,
  withSupportedPythonEnv,
} from "./test-helpers.js";

async function runWithManagedEnvHome(home: string, fn: () => void | Promise<void>): Promise<void> {
  const previousHome = process.env.HM_ARCH_HOME;
  const previousSpec = process.env.HM_ARCH_PIP_SPEC;
  const previousRuntime = process.env.HM_ARCH_RUNTIME;
  process.env.HM_ARCH_HOME = home;
  process.env.HM_ARCH_PIP_SPEC = join(import.meta.dirname, "..", "..", "..");
  process.env.HM_ARCH_RUNTIME = "python";
  try {
    await withExclusiveEditablePipInstall(() => withSupportedPythonEnv(fn));
  } finally {
    if (previousHome === undefined) {
      delete process.env.HM_ARCH_HOME;
    } else {
      process.env.HM_ARCH_HOME = previousHome;
    }
    if (previousSpec === undefined) {
      delete process.env.HM_ARCH_PIP_SPEC;
    } else {
      process.env.HM_ARCH_PIP_SPEC = previousSpec;
    }
    if (previousRuntime === undefined) {
      delete process.env.HM_ARCH_RUNTIME;
    } else {
      process.env.HM_ARCH_RUNTIME = previousRuntime;
    }
  }
}

describe("commands python runtime", () => {
  it("install exits 0 after preparing managed env when supported python is available", {
    skip: !hasSupportedPython(),
  }, async () => {
    const home = mkdtempSync(join(tmpdir(), "hm-arch-cmd-"));
    try {
      await runWithManagedEnvHome(home, async () => {
        await withTempWorkdir(async () => {
          const code = await runParsedCommand({
            command: "install",
            agent: "codex",
            global: false,
            help: false,
          });
          assert.equal(code, 0);
        });
      });
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("upgrade exits 0 when supported python is available", { skip: !hasSupportedPython() }, async () => {
    const home = mkdtempSync(join(tmpdir(), "hm-arch-cmd-up-"));
    try {
      await runWithManagedEnvHome(home, async () => {
        await withTempWorkdir(async () => {
          assert.equal(
            await runParsedCommand({
              command: "install",
              agent: "codex",
              global: false,
              help: false,
            }),
            0,
          );
          assert.equal(
            await runParsedCommand({ command: "upgrade", global: false, help: false }),
            0,
          );
        });
      });
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });
});
