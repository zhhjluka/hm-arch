import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";

import { runParsedCommand } from "../src/commands.js";
import { probePython } from "../src/platform.js";

describe("commands python runtime", () => {
  it("install exits 0 after preparing managed env when python is available", { skip: probePython() === null }, () => {
    const home = mkdtempSync(join(tmpdir(), "hm-arch-cmd-"));
    const previousHome = process.env.HM_ARCH_HOME;
    const previousSpec = process.env.HM_ARCH_PIP_SPEC;
    process.env.HM_ARCH_HOME = home;
    process.env.HM_ARCH_PIP_SPEC = join(import.meta.dirname, "..", "..", "..");
    try {
      const code = runParsedCommand({
        command: "install",
        agent: "codex",
        global: false,
        help: false,
      });
      assert.equal(code, 0);
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
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("upgrade exits 0 when python is available", { skip: probePython() === null }, () => {
    const home = mkdtempSync(join(tmpdir(), "hm-arch-cmd-up-"));
    const previousHome = process.env.HM_ARCH_HOME;
    const previousSpec = process.env.HM_ARCH_PIP_SPEC;
    process.env.HM_ARCH_HOME = home;
    process.env.HM_ARCH_PIP_SPEC = join(import.meta.dirname, "..", "..", "..");
    try {
      assert.equal(
        runParsedCommand({ command: "install", agent: "codex", global: false, help: false }),
        0,
      );
      assert.equal(
        runParsedCommand({ command: "upgrade", global: false, help: false }),
        0,
      );
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
      rmSync(home, { recursive: true, force: true });
    }
  });
});
