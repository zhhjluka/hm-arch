import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { SidecarClient } from "../src/sidecar-client.js";
import {
  createMockClient,
  goldenInitializeResponse,
  loadFixtureJson,
} from "./mock-sidecar.js";

describe("sidecar client", () => {
  it("round-trips search requests against golden fixtures", async () => {
    const { client } = createMockClient({
      search: "golden/03-search-response.json",
    });
    const response = await client.request(
      "search",
      { query: "python preference", top_k: 5 },
      { timeoutMs: 1000 },
    );
    assert.equal(response.ok, true);
    assert.match(String(response.result.context), /untrusted/i);
    await client.close();
  });

  it("times out when the transport does not respond", async () => {
    const { client, transport } = createMockClient({});
    transport.write = () => {
      // Intentionally ignore requests.
    };
    await assert.rejects(
      () => client.request("health", {}, { timeoutMs: 25 }),
      /timed out/i,
    );
    await client.close();
  });

  it("parses initialize negotiation from mock sidecar", async () => {
    const transport = new (await import("./mock-sidecar.js")).MockSidecarTransport(
      (request) => goldenInitializeResponse(request),
    );
    const client = new SidecarClient(transport);
    const response = await client.request(
      "initialize",
      {
        db_path: "/tmp/test.db",
        client_capabilities: ["telemetry.v1"],
      },
      { timeoutMs: 1000 },
    );
    assert.equal(response.ok, true);
    assert.equal(response.result.ready, true);
    await client.close();
  });

  it("returns fail-open remember fixture shape", async () => {
    const { client } = createMockClient({
      remember: "golden/05b-remember-fail-open-response.json",
    });
    const response = await client.request(
      "remember",
      { content: "test fact" },
      { timeoutMs: 1000 },
    );
    assert.equal(response.ok, false);
    assert.equal(response.result.recorded, false);
    const fixture = loadFixtureJson("golden/05b-remember-fail-open-response.json");
    assert.equal(fixture.operation, "remember");
    await client.close();
  });
});
