import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";

import { main } from "../src/cli.js";
import { runParsedCommand } from "../src/commands.js";
import {
  buildHmArchArgv,
  delegateParsedCommand,
  forwardHmArchOutput,
  resolveManagedHmArchExecutable,
  runManagedHmArch,
} from "../src/hm-arch-cli.js";
import { managedHmArchExecutable } from "../src/paths.js";
import {
  hasSupportedPython,
  withExclusiveEditablePipInstall,
  withSupportedPythonEnv,
} from "./test-helpers.js";

const REPO_ROOT = join(import.meta.dirname, "..", "..", "..");

async function runWithManagedEnvHome(home: string, fn: () => void | Promise<void>): Promise<void> {
  const previousHome = process.env.HM_ARCH_HOME;
  const previousSpec = process.env.HM_ARCH_PIP_SPEC;
  process.env.HM_ARCH_HOME = home;
  process.env.HM_ARCH_PIP_SPEC = REPO_ROOT;
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
  }
}

describe("hm-arch CLI delegation", () => {
  it("buildHmArchArgv maps install with agent and --global", () => {
    assert.deepEqual(
      buildHmArchArgv({
        command: "install",
        agent: "codex",
        global: true,
        help: false,
      }),
      ["install", "codex", "--global"],
    );
  });

  it("buildHmArchArgv maps upgrade with agent to hm-arch install", () => {
    assert.deepEqual(
      buildHmArchArgv({
        command: "upgrade",
        agent: "claude-code",
        global: false,
        help: false,
      }),
      ["install", "claude-code"],
    );
  });

  it("buildHmArchArgv returns empty argv for upgrade without agent", () => {
    assert.deepEqual(
      buildHmArchArgv({
        command: "upgrade",
        global: false,
        help: false,
      }),
      [],
    );
  });

  it("runManagedHmArch forwards stdout and stderr", () => {
    const home = mkdtempSync(join(tmpdir(), "hm-arch-delegate-out-"));
    const executable = managedHmArchExecutable(home);
    const stdoutChunks: string[] = [];
    const stderrChunks: string[] = [];
    try {
      const code = runManagedHmArch(["status"], {
        hmArchHome: home,
        exists: (path) => path === executable,
        spawn: () => ({
          status: 0,
          signal: null,
          stdout: "managed-out\n",
          stderr: "managed-err\n",
          pid: 1,
          output: ["", "managed-out\n", "managed-err\n"],
          error: undefined,
        }),
        stdout: { write: (chunk) => stdoutChunks.push(String(chunk)) } as NodeJS.WriteStream,
        stderr: { write: (chunk) => stderrChunks.push(String(chunk)) } as NodeJS.WriteStream,
      });
      assert.equal(code.exitCode, 0);
      assert.equal(stdoutChunks.join(""), "managed-out\n");
      assert.equal(stderrChunks.join(""), "managed-err\n");
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("runManagedHmArch returns non-zero exit codes from hm-arch", () => {
    const home = mkdtempSync(join(tmpdir(), "hm-arch-delegate-exit-"));
    const executable = managedHmArchExecutable(home);
    try {
      const result = runManagedHmArch(["doctor", "codex"], {
        hmArchHome: home,
        exists: (path) => path === executable,
        spawn: () => ({
          status: 3,
          signal: null,
          stdout: "",
          stderr: "codex (project): not_installed\n",
          pid: 1,
          output: ["", "", "codex (project): not_installed\n"],
          error: undefined,
        }),
      });
      assert.equal(result.exitCode, 3);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("resolveManagedHmArchExecutable reports missing CLI", () => {
    const home = mkdtempSync(join(tmpdir(), "hm-arch-delegate-missing-"));
    try {
      const resolved = resolveManagedHmArchExecutable({
        hmArchHome: home,
        exists: () => false,
      });
      assert.ok("error" in resolved);
      assert.match(resolved.error, /hm-arch CLI not found/);
      assert.equal(resolved.exitCode, 1);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("delegateParsedCommand surfaces missing managed CLI on stderr", () => {
    const home = mkdtempSync(join(tmpdir(), "hm-arch-delegate-delegate-"));
    const errors: string[] = [];
    const originalError = console.error;
    console.error = (...args: unknown[]) => {
      errors.push(args.map(String).join(" "));
    };
    try {
      const code = delegateParsedCommand(
        { command: "status", global: false, help: false },
        { hmArchHome: home, exists: () => false },
      );
      assert.equal(code, 1);
      assert.match(errors.join("\n"), /hm-arch CLI not found/);
    } finally {
      console.error = originalError;
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("main rejects unsupported agent before delegation", async () => {
    assert.equal(await main(["install", "vscode"]), 2);
  });

  it("runParsedCommand delegates status to managed hm-arch executable", {
    skip: !hasSupportedPython(),
  }, async () => {
    const home = mkdtempSync(join(tmpdir(), "hm-arch-delegate-smoke-"));
    const previousRuntime = process.env.HM_ARCH_RUNTIME;
    process.env.HM_ARCH_RUNTIME = "python";
    try {
      await runWithManagedEnvHome(home, async () => {
        const code = await runParsedCommand({
          command: "status",
          global: false,
          help: false,
        });
        assert.ok(code === 0 || code === 1);
      });
    } finally {
      if (previousRuntime === undefined) {
        delete process.env.HM_ARCH_RUNTIME;
      } else {
        process.env.HM_ARCH_RUNTIME = previousRuntime;
      }
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("forwardHmArchOutput is a no-op for empty streams", () => {
    assert.doesNotThrow(() =>
      forwardHmArchOutput(
        { stdout: "", stderr: "" },
        {
          stdout: {
            write: () => {
              throw new Error("should not write stdout");
            },
          } as NodeJS.WriteStream,
          stderr: {
            write: () => {
              throw new Error("should not write stderr");
            },
          } as NodeJS.WriteStream,
        },
      ),
    );
  });
});
