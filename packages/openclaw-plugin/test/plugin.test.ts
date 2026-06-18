import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { describe, it } from "node:test";

import {
  TurnCaptureTracker,
  buildRequest,
  fingerprintTurn,
  parseResponseLine,
} from "../dist/index.js";

describe("openclaw plugin capture", () => {
  it("deduplicates processed turns exactly once", () => {
    const tracker = new TurnCaptureTracker();
    assert.equal(tracker.shouldCapture("sess", "hello", "world"), true);
    assert.equal(tracker.shouldCapture("sess", "hello", "world"), false);
    assert.equal(
      fingerprintTurn("sess", "hello", "world"),
      fingerprintTurn("sess", "hello", "world"),
    );
  });
});

describe("sidecar protocol helpers", () => {
  it("builds initialize requests with correlation ids", () => {
    const request = buildRequest("initialize", { db_path: "/tmp/test.db" });
    assert.equal(request.operation, "initialize");
    assert.equal(request.protocol_version, "1.0");
    assert.ok(request.correlation_id.length > 0);
  });
});

describe("mock sidecar fixtures", () => {
  it("parses golden initialize response shape", async () => {
    const mock = spawn("node", ["-e", `
      const fs = require('node:fs');
      const path = require('node:path');
      const fixture = JSON.parse(fs.readFileSync(path.join('fixtures/sidecar-protocol/golden/01-initialize-response.json'), 'utf8'));
      process.stdout.write(JSON.stringify(fixture) + '\\n');
    `], { cwd: new URL("../../..", import.meta.url).pathname });

    const line = await new Promise<string>((resolve, reject) => {
      const reader = createInterface({ input: mock.stdout });
      reader.on("line", (value) => resolve(value));
      mock.on("error", reject);
      mock.on("close", (code) => {
        if (code !== 0) {
          reject(new Error(`mock sidecar exited with ${code}`));
        }
      });
    });

    const response = parseResponseLine(line);
    assert.equal(response.ok, true);
    assert.equal(response.operation, "initialize");
    assert.equal(response.result.ready, true);
  });
});
