import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

import {
  CURRENT_PROTOCOL_VERSION,
  FAIL_OPEN_OPERATIONS,
  SUPPORTED_OPERATIONS,
  failOpenRecordTurn,
  failOpenRemember,
  failOpenSearch,
  negotiateCapabilities,
  negotiateProtocolVersion,
  parseSidecarRequest,
  parseSidecarRequestLine,
  parseSidecarResponse,
  parseSidecarResponseLine,
  ProtocolValidationError,
  validateOperation,
  validateProtocolVersion,
} from "../src/sidecar-protocol.js";
import { FIXTURES_ROOT, loadFixtureJson } from "./mock-sidecar.js";

const manifest = JSON.parse(
  readFileSync(join(FIXTURES_ROOT, "manifest.json"), "utf8"),
) as {
  fixtures: Array<{
    id: string;
    request: string;
    response: string;
    invalid_request?: boolean;
  }>;
  transcript: string;
};

describe("sidecar protocol contract", () => {
  it("lists all required operations", () => {
    assert.deepEqual(new Set(SUPPORTED_OPERATIONS), new Set([
      "initialize",
      "health",
      "search",
      "remember",
      "forget",
      "record_turn",
      "consolidate",
      "shutdown",
    ]));
  });

  it("marks recall/capture operations as fail-open", () => {
    assert.deepEqual(FAIL_OPEN_OPERATIONS, [
      "search",
      "remember",
      "record_turn",
    ]);
  });

  for (const entry of manifest.fixtures) {
    it(`parses golden fixture ${entry.id}`, () => {
      const request = loadFixtureJson(entry.request);
      const response = loadFixtureJson(entry.response);
      if (entry.invalid_request) {
        assert.throws(
          () => parseSidecarRequest(request),
          ProtocolValidationError,
        );
        return;
      }
      const parsedRequest = parseSidecarRequest(request);
      const parsedResponse = parseSidecarResponse(response);
      assert.equal(parsedResponse.correlation_id, parsedRequest.correlation_id);
      assert.equal(parsedResponse.operation, parsedRequest.operation);
    });
  }

  it("parses full-session JSONL transcript", () => {
    const lines = readFileSync(join(FIXTURES_ROOT, manifest.transcript), "utf8")
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    assert.equal(lines.length % 2, 0);
    for (let index = 0; index < lines.length; index += 2) {
      const request = parseSidecarRequestLine(lines[index]!);
      const response = parseSidecarResponseLine(lines[index + 1]!);
      assert.equal(response.correlation_id, request.correlation_id);
      assert.equal(response.operation, request.operation);
    }
  });

  it("negotiates protocol versions within the same major", () => {
    assert.equal(negotiateProtocolVersion("1.2", "1.0"), "1.0");
    assert.throws(
      () => validateProtocolVersion("2.0", CURRENT_PROTOCOL_VERSION),
      ProtocolValidationError,
    );
  });

  it("negotiates capability intersection", () => {
    const { serverCapabilities, negotiatedCapabilities } = negotiateCapabilities(
      ["telemetry.v1", "unknown.v9"],
      ["telemetry.v1", "health.deep.v1"],
    );
    assert.deepEqual(serverCapabilities, ["telemetry.v1", "health.deep.v1"]);
    assert.deepEqual(negotiatedCapabilities, ["telemetry.v1"]);
  });

  it("returns safe fail-open search responses", () => {
    const response = failOpenSearch("corr-1", "database locked");
    assert.equal(response.ok, false);
    assert.equal(response.result.context, "");
    assert.equal(response.error?.retryable, true);
  });

  it("returns safe fail-open remember responses", () => {
    const response = failOpenRemember("corr-2", "write failed");
    assert.equal(response.ok, false);
    assert.equal(response.result.memory_id, null);
    assert.equal(response.result.recorded, false);
  });

  it("returns safe fail-open record_turn responses", () => {
    const response = failOpenRecordTurn("corr-3", "capture failed");
    assert.equal(response.ok, false);
    assert.deepEqual(response.result.memory_ids, []);
    assert.equal(response.result.recorded_count, 0);
  });

  it("rejects unsupported operations", () => {
    assert.throws(() => validateOperation("noop"), ProtocolValidationError);
  });
});
