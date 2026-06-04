import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { parseCliArgs } from "../src/parse-args.js";

describe("parseCliArgs", () => {
  it("parses install with agent and --global", () => {
    const parsed = parseCliArgs(["install", "codex", "--global"]);
    assert.equal(parsed.command, "install");
    assert.equal(parsed.agent, "codex");
    assert.equal(parsed.global, true);
  });

  it("parses optional agent for status", () => {
    const parsed = parseCliArgs(["status", "claude-code"]);
    assert.equal(parsed.command, "status");
    assert.equal(parsed.agent, "claude-code");
  });

  it("parses upgrade without agent", () => {
    const parsed = parseCliArgs(["upgrade"]);
    assert.equal(parsed.command, "upgrade");
    assert.equal(parsed.agent, undefined);
  });

  it("rejects unknown command", () => {
    const parsed = parseCliArgs(["bootstrap"]);
    assert.match(parsed.error ?? "", /Unknown command/);
  });

  it("rejects unsupported agent", () => {
    const parsed = parseCliArgs(["install", "vscode"]);
    assert.match(parsed.error ?? "", /Unsupported agent/);
  });

  it("requires agent for uninstall", () => {
    const parsed = parseCliArgs(["uninstall"]);
    assert.match(parsed.error ?? "", /requires an agent/);
  });

  it("rejects extra positional arguments", () => {
    const parsed = parseCliArgs(["doctor", "codex", "extra"]);
    assert.match(parsed.error ?? "", /Unexpected argument/);
  });

  it("rejects unknown flags on status", () => {
    const parsed = parseCliArgs(["status", "--bogus"]);
    assert.match(parsed.error ?? "", /Unknown option "--bogus"/);
  });

  it("rejects unknown flags on install", () => {
    const parsed = parseCliArgs(["install", "codex", "--bogus"]);
    assert.match(parsed.error ?? "", /Unknown option "--bogus"/);
  });

  it("rejects mistyped global flag", () => {
    const parsed = parseCliArgs(["install", "codex", "--globall"]);
    assert.match(parsed.error ?? "", /Unknown option "--globall"/);
  });
});
