import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { describe, it } from "node:test";

import { runParsedCommand } from "../src/commands.js";
import {
  detectPlatform,
  environmentDiagnostics,
  hasBlockingDiagnostics,
} from "../src/platform.js";
import { detectReleaseTarget } from "../src/release-target.js";
import { hasStandaloneFixture, withStandaloneRuntimeEnv } from "./test-helpers.js";

describe("clean-machine standalone environment (MEM-64)", () => {
  it("does not block on missing Python when standalone target is supported", () => {
    const target = detectReleaseTarget();
    if (!target) {
      return;
    }

    const previousRuntime = process.env.HM_ARCH_RUNTIME;
    process.env.HM_ARCH_RUNTIME = "standalone";
    try {
      const diagnostics = environmentDiagnostics(
        detectPlatform({
          platform: process.platform,
          arch: process.arch,
          nodeVersion: process.version,
          python: null,
        }),
      );
      assert.equal(hasBlockingDiagnostics(diagnostics), false);
      const pythonDiag = diagnostics.find((item) => item.code === "python_missing");
      assert.ok(pythonDiag);
      assert.equal(pythonDiag.level, "warning");
    } finally {
      if (previousRuntime === undefined) {
        delete process.env.HM_ARCH_RUNTIME;
      } else {
        process.env.HM_ARCH_RUNTIME = previousRuntime;
      }
    }
  });

  it("doctor succeeds without Python when standalone fixture is installed", {
    skip: !hasStandaloneFixture() || detectReleaseTarget() === null,
  }, async () => {
    await withStandaloneRuntimeEnv({ stripPython: true }, async () => {
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
        await runParsedCommand({
          command: "doctor",
          agent: "codex",
          global: false,
          help: false,
        }),
        0,
      );
    });
  });
});

describe("clean-machine integration management via standalone executable (MEM-64)", () => {
  it("manages Codex hooks without Python on PATH", {
    skip: !hasStandaloneFixture() || detectReleaseTarget() === null,
  }, async () => {
    await withStandaloneRuntimeEnv({ stripPython: true }, async ({ workdir }) => {
      assert.equal(
        await runParsedCommand({
          command: "install",
          agent: "codex",
          global: false,
          help: false,
        }),
        0,
      );
      const hooksPath = `${workdir}/.codex/hooks.json`;
      assert.ok(existsSync(hooksPath));

      assert.equal(
        await runParsedCommand({
          command: "status",
          agent: "codex",
          global: false,
          help: false,
        }),
        0,
      );

      assert.equal(
        await runParsedCommand({
          command: "doctor",
          agent: "codex",
          global: false,
          help: false,
        }),
        0,
      );

      assert.equal(
        await runParsedCommand({
          command: "uninstall",
          agent: "codex",
          global: false,
          help: false,
        }),
        0,
      );
      assert.equal(existsSync(hooksPath), false);
    });
  });

  it("manages Claude Code hooks without Python on PATH", {
    skip: !hasStandaloneFixture() || detectReleaseTarget() === null,
  }, async () => {
    await withStandaloneRuntimeEnv({ stripPython: true }, async ({ workdir }) => {
      assert.equal(
        await runParsedCommand({
          command: "install",
          agent: "claude-code",
          global: false,
          help: false,
        }),
        0,
      );
      const hooksPath = `${workdir}/.claude/settings.json`;
      assert.ok(existsSync(hooksPath));

      assert.equal(
        await runParsedCommand({
          command: "status",
          agent: "claude-code",
          global: false,
          help: false,
        }),
        0,
      );

      assert.equal(
        await runParsedCommand({
          command: "doctor",
          agent: "claude-code",
          global: false,
          help: false,
        }),
        0,
      );

      assert.equal(
        await runParsedCommand({
          command: "uninstall",
          agent: "claude-code",
          global: false,
          help: false,
        }),
        0,
      );
      assert.equal(existsSync(hooksPath), false);
    });
  });

  it("reports Hermes install as unsupported and still runs status/doctor", {
    skip: !hasStandaloneFixture() || detectReleaseTarget() === null,
  }, async () => {
    await withStandaloneRuntimeEnv({ stripPython: true }, async () => {
      assert.equal(
        await runParsedCommand({
          command: "install",
          agent: "hermes",
          global: false,
          help: false,
        }),
        2,
      );

      const statusCode = await runParsedCommand({
        command: "status",
        agent: "hermes",
        global: false,
        help: false,
      });
      assert.ok(statusCode === 0 || statusCode === 1);

      const doctorCode = await runParsedCommand({
        command: "doctor",
        agent: "hermes",
        global: false,
        help: false,
      });
      assert.ok(doctorCode === 0 || doctorCode === 1);
    });
  });
});
