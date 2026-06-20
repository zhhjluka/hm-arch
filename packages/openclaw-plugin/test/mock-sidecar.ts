import { EventEmitter } from "node:events";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  CURRENT_PROTOCOL_VERSION,
  negotiateCapabilities,
  negotiateProtocolVersion,
  parseSidecarRequest,
  type SidecarOperation,
  type SidecarRequest,
  type SidecarResponse,
} from "../src/sidecar-protocol.js";
import { SidecarClient } from "../src/sidecar-client.js";
import type { SidecarTransport } from "../src/sidecar-client.js";

export const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), "../../..");
export const FIXTURES_ROOT = join(REPO_ROOT, "fixtures/sidecar-protocol");

export function loadFixtureJson(relativePath: string): Record<string, unknown> {
  return JSON.parse(
    readFileSync(join(FIXTURES_ROOT, relativePath), "utf8"),
  ) as Record<string, unknown>;
}

export class MockSidecarTransport implements SidecarTransport {
  private readonly emitter = new EventEmitter();
  private closed = false;
  readonly requests: SidecarRequest[] = [];

  constructor(
    private readonly responder: (request: SidecarRequest) => SidecarResponse,
  ) {}

  write(line: string): void {
    if (this.closed) {
      return;
    }
    const request = parseSidecarRequest(JSON.parse(line.trim()));
    this.requests.push(request);
    const response = this.responder(request);
    queueMicrotask(() => {
      if (!this.closed) {
        this.emitter.emit("data", `${JSON.stringify(response)}\n`);
      }
    });
  }

  onData(handler: (chunk: string) => void): void {
    this.emitter.on("data", handler);
  }

  onClose(handler: (code: number | null) => void): void {
    this.emitter.on("close", () => handler(0));
  }

  async close(): Promise<void> {
    this.closed = true;
    this.emitter.emit("close");
  }
}

export function fixtureResponder(
  mapping: Partial<Record<SidecarOperation, string>>,
): (request: SidecarRequest) => SidecarResponse {
  return (request) => {
    const fixturePath = mapping[request.operation];
    if (!fixturePath) {
      return {
        protocol_version: CURRENT_PROTOCOL_VERSION,
        correlation_id: request.correlation_id,
        operation: request.operation,
        ok: false,
        result: {},
        error: {
          code: "UNSUPPORTED_OPERATION",
          message: `no fixture for ${request.operation}`,
          retryable: false,
        },
      };
    }
    const fixture = loadFixtureJson(fixturePath) as SidecarResponse;
    return {
      ...fixture,
      correlation_id: request.correlation_id,
      operation: request.operation,
    };
  };
}

export function createMockClient(
  mapping: Partial<Record<SidecarOperation, string>>,
): { client: SidecarClient; transport: MockSidecarTransport } {
  const transport = new MockSidecarTransport(fixtureResponder(mapping));
  const client = new SidecarClient(transport);
  return { client, transport };
}

export function goldenInitializeResponse(request: SidecarRequest): SidecarResponse {
  const params = request.params;
  const clientCaps = Array.isArray(params.client_capabilities)
    ? params.client_capabilities.map(String)
    : [];
  const negotiated = negotiateCapabilities(clientCaps);
  return {
    protocol_version: CURRENT_PROTOCOL_VERSION,
    correlation_id: request.correlation_id,
    operation: "initialize",
    ok: true,
    result: {
      ready: true,
      negotiated_protocol_version: negotiateProtocolVersion(request.protocol_version),
      server_capabilities: negotiated.serverCapabilities,
      negotiated_capabilities: negotiated.negotiatedCapabilities,
      db_path: String(params.db_path ?? ":memory:"),
    },
    error: null,
  };
}
