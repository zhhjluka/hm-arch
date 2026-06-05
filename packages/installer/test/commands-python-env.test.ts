import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";

function withTempWorkdir<T>(fn: (workdir: string) => void): void {
  const workdir = mkdtempSync(join(tmpdir(), "hm-arch-cmd-cwd-"));
  const previous = process.cwd();
  process.chdir(workdir);
  try {
    fn(workdir);
  } finally {
    process.chdir(previous);
    rmSync(workdir, { recursive: true, force: true });
  }
}

import { runParsedCommand } from "../src/commands.js";
import { hasSupportedPython, withSupportedPythonEnv } from "./test-helpers.js";

function runWithManagedEnvHome(home: string, fn: () => void): void {
  const previousHome = process.env.HM_ARCH_HOME;
  const previousSpec = process.env.HM_ARCH_PIP_SPEC;
  process.env.HM_ARCH_HOME = home;
  process.env.HM_ARCH_PIP_SPEC = join(import.meta.dirname, "..", "..", "..");
  try {
    withSupportedPythonEnv(fn);
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
  }
}

describe("commands python runtime", () => {
  it("install exits 0 after preparing managed env when supported python is available", {
    skip: !hasSupportedPython(),
  }, () => {
    const home = mkdtempSync(join(tmpdir(), "hm-arch-cmd-"));
    try {
      runWithManagedEnvHome(home, () => {
        withTempWorkdir(() => {
          const code = runParsedCommand({
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

  it("upgrade exits 0 when supported python is available", { skip: !hasSupportedPython() }, () => {
    const home = mkdtempSync(join(tmpdir(), "hm-arch-cmd-up-"));
    try {
      runWithManagedEnvHome(home, () => {
        withTempWorkdir(() => {
          assert.equal(
            runParsedCommand({ command: "install", agent: "codex", global: false, help: false }),
            0,
          );
          assert.equal(
            runParsedCommand({ command: "upgrade", global: false, help: false }),
            0,
          );
        });
      });
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });
});
