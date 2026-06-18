import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { describe, it } from "node:test";

import { SidecarManager } from "../src/sidecar-manager.js";
import {
  fixtureResponder,
  goldenInitializeResponse,
  MockSidecarTransport,
} from "./mock-sidecar.js";

function createFakeSpawn(transportFactory: () => MockSidecarTransport) {
  return (_command: string, _args: string[]) => {
    const transport = transportFactory();
    const child = new EventEmitter() as EventEmitter & {
      stdin: { write: (line: string) => void; end: () => void };
      stdout: EventEmitter;
      stderr: EventEmitter;
      killed: boolean;
      kill: () => void;
    };
    child.stdin = {
      write: (line: string) => transport.write(line),
      end: () => undefined,
    };
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    child.killed = false;
    child.kill = () => {
      if (!child.killed) {
        child.killed = true;
        child.emit("close", 0);
      }
    };

    transport.onData((chunk) => child.stdout.emit("data", chunk));

    return child;
  };
}

describe("sidecar manager", () => {
  it("initializes and serves search requests", async () => {
    const requests: string[] = [];
    const manager = new SidecarManager({
      command: ["mock-sidecar"],
      dbPath: "/tmp/hm-arch.db",
      requestTimeoutMs: 1000,
      startupTimeoutMs: 1000,
      maxRestartBackoffMs: 1000,
      spawn: createFakeSpawn(
        () =>
          new MockSidecarTransport((request) => {
            requests.push(request.operation);
            if (request.operation === "initialize") {
              return goldenInitializeResponse(request);
            }
            if (request.operation === "search") {
              return fixtureResponder({ search: "golden/03-search-response.json" })(
                request,
              );
            }
            return fixtureResponder({ shutdown: "golden/09-shutdown-response.json" })(
              request,
            );
          }),
      ),
    });

    await manager.start();
    const response = await manager.search({
      query: "python",
      topK: 3,
      maxContextChars: 500,
    });
    assert.equal(response.ok, true);
    assert.ok(requests.includes("initialize"));
    await manager.stop();
    assert.ok(requests.includes("shutdown"));
  });

  it("returns fail-open search results without throwing", async () => {
    const manager = new SidecarManager({
      command: ["mock-sidecar"],
      dbPath: "/tmp/hm-arch.db",
      requestTimeoutMs: 1000,
      startupTimeoutMs: 1000,
      maxRestartBackoffMs: 1000,
      spawn: createFakeSpawn(
        () =>
          new MockSidecarTransport((request) => {
            if (request.operation === "initialize") {
              return goldenInitializeResponse(request);
            }
            if (request.operation === "search") {
              return fixtureResponder({
                search: "golden/04-search-fail-open-response.json",
              })(request);
            }
            return fixtureResponder({ shutdown: "golden/09-shutdown-response.json" })(
              request,
            );
          }),
      ),
    });
    await manager.start();
    const response = await manager.search({
      query: "missing",
      topK: 3,
      maxContextChars: 500,
    });
    assert.equal(response.ok, false);
    assert.equal(response.result.context, "");
    await manager.stop();
  });
});
