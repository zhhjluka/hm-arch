import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
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

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "../../..");
const fixturesRoot = join(repoRoot, "fixtures/sidecar-protocol");
const manifest = JSON.parse(
  readFileSync(join(fixturesRoot, "manifest.json"), "utf8"),
) as {
  fixtures: Array<{
    id: string;
    request: string;
    response: string;
    invalid_request?: boolean;
  }>;
  transcript: string;
};

function loadJson(relativePath: string): Record<string, unknown> {
  return JSON.parse(
    readFileSync(join(fixturesRoot, relativePath), "utf8"),
  ) as Record<string, unknown>;
}

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
    assert.deepEqual(serverCapabilities, [
      "telemetry.v1",
      "health.deep.v1",
    ]);
    assert.deepEqual(negotiatedCapabilities, ["telemetry.v1"]);
  });

  for (const entry of manifest.fixtures) {
    it(`parses golden fixture ${entry.id}`, () => {
      const request = loadJson(entry.request);
      const response = loadJson(entry.response);
      if (entry.invalid_request) {
        assert.throws(
          () => parseSidecarRequest(request),
          ProtocolValidationError,
        );
      } else {
        const parsedRequest = parseSidecarRequest(request);
        const parsedResponse = parseSidecarResponse(response);
        assert.equal(parsedResponse.correlation_id, parsedRequest.correlation_id);
        assert.equal(parsedResponse.operation, parsedRequest.operation);
        return;
      }
      const parsedResponse = parseSidecarResponse(response);
      assert.equal(parsedResponse.correlation_id, request.correlation_id);
      assert.equal(parsedResponse.operation, request.operation);
    });
  }

  it("parses full-session JSONL transcript", () => {
    const lines = readFileSync(join(fixturesRoot, manifest.transcript), "utf8")
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

  it("returns safe fail-open search responses", () => {
    const response = failOpenSearch("corr-1", "database locked");
    assert.equal(response.ok, false);
    assert.equal(response.result.context, "");
    assert.equal(response.result.result_count, 0);
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

  it("rejects requests missing operation", () => {
    assert.throws(
      () =>
        parseSidecarRequest({
          protocol_version: "1.0",
          correlation_id: "x",
          params: {},
        }),
      ProtocolValidationError,
    );
  });

  it("rejects responses missing operation", () => {
    assert.throws(
      () =>
        parseSidecarResponse({
          protocol_version: "1.0",
          correlation_id: "x",
          ok: true,
          result: {},
          error: null,
        }),
      ProtocolValidationError,
    );
  });

  it("rejects non-boolean db_reachable on health responses", () => {
    assert.throws(
      () =>
        parseSidecarResponse({
          protocol_version: "1.0",
          correlation_id: "x",
          operation: "health",
          ok: true,
          result: { status: "healthy", db_reachable: "false" },
          error: null,
        }),
      ProtocolValidationError,
    );
  });

  it("rejects string integer fields on success responses", () => {
    assert.throws(
      () =>
        parseSidecarResponse({
          protocol_version: "1.0",
          correlation_id: "x",
          operation: "search",
          ok: true,
          result: {
            context: "",
            hits: [],
            result_count: "0",
            truncated: false,
          },
          error: null,
        }),
      ProtocolValidationError,
    );
  });

  it("rejects malformed search hit fields", () => {
    assert.throws(
      () =>
        parseSidecarResponse({
          protocol_version: "1.0",
          correlation_id: "x",
          operation: "search",
          ok: true,
          result: {
            context: "",
            hits: [
              {
                memory_id: "mem-1",
                layer: "3",
                content: "hello",
                score: 0.8,
                retention: 0.9,
              },
            ],
            result_count: 1,
            truncated: false,
          },
          error: null,
        }),
      ProtocolValidationError,
    );
  });

  it("accepts initialize errors without success-only result fields", () => {
    const response = parseSidecarResponse({
      protocol_version: "1.0",
      correlation_id: "x",
      operation: "initialize",
      ok: false,
      result: {},
      error: {
        code: "STORAGE_ERROR",
        message: "cannot open database",
        retryable: true,
      },
    });
    assert.equal(response.ok, false);
    assert.deepEqual(response.result, {});
    assert.equal(response.error?.code, "STORAGE_ERROR");
  });

  it("rejects successful responses that include error", () => {
    assert.throws(
      () =>
        parseSidecarResponse({
          protocol_version: "1.0",
          correlation_id: "x",
          operation: "health",
          ok: true,
          result: { status: "healthy", db_reachable: true },
          error: {
            code: "INTERNAL_ERROR",
            message: "should not be here",
            retryable: true,
          },
        }),
      ProtocolValidationError,
    );
  });

  it("rejects failed responses without error", () => {
    assert.throws(
      () =>
        parseSidecarResponse({
          protocol_version: "1.0",
          correlation_id: "x",
          operation: "search",
          ok: false,
          result: {
            context: "",
            hits: [],
            result_count: 0,
            truncated: false,
          },
          error: null,
        }),
      ProtocolValidationError,
    );
  });
});
