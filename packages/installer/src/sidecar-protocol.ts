/**
 * JSONL stdio sidecar protocol types and validators for OpenClaw plugin mocks.
 *
 * Contract: docs/sidecar-protocol.md
 * Golden fixtures: fixtures/sidecar-protocol/
 */

export const CURRENT_PROTOCOL_VERSION = "1.0";

export const SUPPORTED_OPERATIONS = [
  "initialize",
  "health",
  "search",
  "remember",
  "forget",
  "record_turn",
  "consolidate",
  "shutdown",
] as const;

export type SidecarOperation = (typeof SUPPORTED_OPERATIONS)[number];

export const FAIL_OPEN_OPERATIONS: readonly SidecarOperation[] = [
  "search",
  "remember",
  "record_turn",
];

export type StructuredError = {
  code: string;
  message: string;
  retryable: boolean;
  details?: Record<string, unknown>;
};

export type SidecarTelemetry = {
  query_latency_ms?: number;
  hit_count?: number;
  returned_characters?: number;
  returned_tokens?: number;
  storage_latency_ms?: number;
};

export type SidecarRequest = {
  protocol_version: string;
  correlation_id: string;
  operation: SidecarOperation;
  params: Record<string, unknown>;
  timeout_ms?: number;
};

export type SidecarResponse = {
  protocol_version: string;
  correlation_id: string;
  operation: SidecarOperation;
  ok: boolean;
  result: Record<string, unknown>;
  telemetry?: SidecarTelemetry | null;
  error?: StructuredError | null;
};

export class ProtocolValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ProtocolValidationError";
  }
}

function parseVersion(version: string): [number, number] {
  const parts = version.split(".", 2);
  if (
    parts.length !== 2 ||
    !/^\d+$/.test(parts[0] ?? "") ||
    !/^\d+$/.test(parts[1] ?? "")
  ) {
    throw new ProtocolValidationError(
      `protocol_version must be MAJOR.MINOR, got ${JSON.stringify(version)}`,
    );
  }
  return [Number(parts[0]), Number(parts[1])];
}

export function validateProtocolVersion(
  version: string,
  serverVersion: string = CURRENT_PROTOCOL_VERSION,
): void {
  const client = parseVersion(version);
  const server = parseVersion(serverVersion);
  if (client[0] !== server[0]) {
    throw new ProtocolValidationError(
      `Incompatible protocol major version ${JSON.stringify(version)}; server is ${JSON.stringify(serverVersion)}`,
    );
  }
}

export function negotiateProtocolVersion(
  clientVersion: string,
  serverVersion: string = CURRENT_PROTOCOL_VERSION,
): string {
  validateProtocolVersion(clientVersion, serverVersion);
  const client = parseVersion(clientVersion);
  const server = parseVersion(serverVersion);
  return `${client[0]}.${Math.min(client[1], server[1])}`;
}

export function negotiateCapabilities(
  clientCapabilities: readonly string[],
  serverCapabilities: readonly string[] = [
    "telemetry.v1",
    "forget.by_query.v1",
    "health.deep.v1",
  ],
): { serverCapabilities: string[]; negotiatedCapabilities: string[] } {
  const negotiated = clientCapabilities.filter((tag) =>
    serverCapabilities.includes(tag),
  );
  return {
    serverCapabilities: [...serverCapabilities],
    negotiatedCapabilities: negotiated,
  };
}

export function validateOperation(value: unknown): SidecarOperation {
  if (typeof value !== "string") {
    throw new ProtocolValidationError("operation must be a string");
  }
  const normalized = value.trim().toLowerCase();
  if (!(SUPPORTED_OPERATIONS as readonly string[]).includes(normalized)) {
    throw new ProtocolValidationError(
      `Unsupported operation ${JSON.stringify(value)}. Supported operations: ${SUPPORTED_OPERATIONS.join(", ")}`,
    );
  }
  return normalized as SidecarOperation;
}

function requireObject(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ProtocolValidationError(`${label} must be a JSON object`);
  }
  return value as Record<string, unknown>;
}

function requireString(value: unknown, key: string): string {
  if (typeof value !== "string") {
    throw new ProtocolValidationError(`${key} must be a string`);
  }
  const stripped = value.trim();
  if (!stripped) {
    throw new ProtocolValidationError(`${key} must be a non-empty string`);
  }
  return stripped;
}

function optionalString(
  data: Record<string, unknown>,
  key: string,
): string | undefined {
  if (!(key in data)) {
    return undefined;
  }
  const value = data[key];
  if (value === null || value === undefined) {
    return undefined;
  }
  if (typeof value !== "string") {
    throw new ProtocolValidationError(`${key} must be a string`);
  }
  const stripped = value.trim();
  return stripped || undefined;
}

function optionalInt(
  data: Record<string, unknown>,
  key: string,
): number | undefined {
  if (!(key in data)) {
    return undefined;
  }
  const value = data[key];
  if (value === null || value === undefined) {
    return undefined;
  }
  if (typeof value === "boolean") {
    throw new ProtocolValidationError(`${key} must be an integer`);
  }
  if (typeof value !== "number") {
    throw new ProtocolValidationError(`${key} must be an integer`);
  }
  if (!Number.isInteger(value)) {
    throw new ProtocolValidationError(`${key} must be an integer`);
  }
  return value;
}

function validateParams(
  operation: SidecarOperation,
  params: Record<string, unknown>,
): void {
  switch (operation) {
    case "initialize":
      requireString(params.db_path, "db_path");
      break;
    case "search": {
      const query = optionalString(params, "query");
      if (!query) {
        throw new ProtocolValidationError("search requires a non-empty query");
      }
      const topK = optionalInt(params, "top_k");
      if (topK !== undefined && topK < 1) {
        throw new ProtocolValidationError("top_k must be >= 1");
      }
      break;
    }
    case "remember": {
      const content = optionalString(params, "content");
      if (!content) {
        throw new ProtocolValidationError("remember requires non-empty content");
      }
      break;
    }
    case "forget": {
      const memoryIds = params.memory_ids;
      const query = optionalString(params, "query");
      const hasIds = Array.isArray(memoryIds) && memoryIds.length > 0;
      if (!hasIds && !query) {
        throw new ProtocolValidationError("forget requires memory_ids or query");
      }
      break;
    }
    case "record_turn": {
      const user = optionalString(params, "user_message") ?? "";
      const agent = optionalString(params, "agent_message") ?? "";
      if (!user && !agent) {
        throw new ProtocolValidationError(
          "record_turn requires at least one non-empty user_message or agent_message",
        );
      }
      break;
    }
    case "health":
    case "consolidate":
    case "shutdown":
      break;
    default:
      throw new ProtocolValidationError(`Unsupported operation ${operation}`);
  }
}

export function parseSidecarRequest(data: unknown): SidecarRequest {
  const payload = requireObject(data, "payload");
  const protocolVersion = requireString(payload.protocol_version, "protocol_version");
  validateProtocolVersion(protocolVersion);
  const correlationId = requireString(payload.correlation_id, "correlation_id");
  const operation = validateOperation(payload.operation);
  const params = requireObject(payload.params ?? {}, "params");
  validateParams(operation, params);
  const timeoutMs = optionalInt(payload, "timeout_ms");
  if (timeoutMs !== undefined && timeoutMs < 1) {
    throw new ProtocolValidationError("timeout_ms must be >= 1");
  }
  const request: SidecarRequest = {
    protocol_version: protocolVersion,
    correlation_id: correlationId,
    operation,
    params,
  };
  if (timeoutMs !== undefined) {
    request.timeout_ms = timeoutMs;
  }
  return request;
}

export function parseSidecarResponse(data: unknown): SidecarResponse {
  const payload = requireObject(data, "payload");
  const protocolVersion = requireString(payload.protocol_version, "protocol_version");
  validateProtocolVersion(protocolVersion);
  const correlationId = requireString(payload.correlation_id, "correlation_id");
  const operation = validateOperation(payload.operation);
  if (typeof payload.ok !== "boolean") {
    throw new ProtocolValidationError("ok must be a boolean");
  }
  const result = requireObject(payload.result ?? {}, "result");
  let error: StructuredError | null = null;
  if (payload.error !== null && payload.error !== undefined) {
    const err = requireObject(payload.error, "error");
    error = {
      code: requireString(err.code, "error.code"),
      message: requireString(err.message, "error.message"),
      retryable:
        typeof err.retryable === "boolean"
          ? err.retryable
          : (() => {
              throw new ProtocolValidationError("error.retryable must be a boolean");
            })(),
      ...(typeof err.details === "object" &&
      err.details !== null &&
      !Array.isArray(err.details)
        ? { details: err.details as Record<string, unknown> }
        : {}),
    };
  }
  let telemetry: SidecarTelemetry | null | undefined;
  if (payload.telemetry === null) {
    telemetry = null;
  } else if (payload.telemetry !== undefined) {
    telemetry = requireObject(payload.telemetry, "telemetry") as SidecarTelemetry;
  }
  return {
    protocol_version: protocolVersion,
    correlation_id: correlationId,
    operation,
    ok: payload.ok,
    result,
    telemetry,
    error,
  };
}

export function parseSidecarRequestLine(line: string): SidecarRequest {
  const stripped = line.trim();
  if (!stripped) {
    throw new ProtocolValidationError("request line must not be empty");
  }
  return parseSidecarRequest(JSON.parse(stripped));
}

export function parseSidecarResponseLine(line: string): SidecarResponse {
  const stripped = line.trim();
  if (!stripped) {
    throw new ProtocolValidationError("response line must not be empty");
  }
  return parseSidecarResponse(JSON.parse(stripped));
}

export function structuredError(
  code: string,
  message: string,
  options: { retryable: boolean; details?: Record<string, unknown> },
): StructuredError {
  return {
    code,
    message,
    retryable: options.retryable,
    ...(options.details ? { details: options.details } : {}),
  };
}

export function failOpenSearch(
  correlationId: string,
  message: string,
  options: {
    protocolVersion?: string;
    code?: string;
    retryable?: boolean;
    telemetry?: SidecarTelemetry;
  } = {},
): SidecarResponse {
  return {
    protocol_version: options.protocolVersion ?? CURRENT_PROTOCOL_VERSION,
    correlation_id: correlationId,
    operation: "search",
    ok: false,
    result: {
      context: "",
      hits: [],
      result_count: 0,
      truncated: false,
    },
    telemetry: options.telemetry ?? {
      query_latency_ms: 0,
      hit_count: 0,
      returned_characters: 0,
      returned_tokens: 0,
    },
    error: structuredError(options.code ?? "STORAGE_ERROR", message, {
      retryable: options.retryable ?? true,
    }),
  };
}

export function failOpenRemember(
  correlationId: string,
  message: string,
  options: {
    protocolVersion?: string;
    code?: string;
    retryable?: boolean;
    telemetry?: SidecarTelemetry;
  } = {},
): SidecarResponse {
  return {
    protocol_version: options.protocolVersion ?? CURRENT_PROTOCOL_VERSION,
    correlation_id: correlationId,
    operation: "remember",
    ok: false,
    result: {
      memory_id: null,
      recorded: false,
    },
    telemetry: options.telemetry ?? { storage_latency_ms: 0 },
    error: structuredError(options.code ?? "STORAGE_ERROR", message, {
      retryable: options.retryable ?? true,
    }),
  };
}

export function failOpenRecordTurn(
  correlationId: string,
  message: string,
  options: {
    protocolVersion?: string;
    code?: string;
    retryable?: boolean;
    telemetry?: SidecarTelemetry;
  } = {},
): SidecarResponse {
  return {
    protocol_version: options.protocolVersion ?? CURRENT_PROTOCOL_VERSION,
    correlation_id: correlationId,
    operation: "record_turn",
    ok: false,
    result: {
      memory_ids: [],
      recorded_count: 0,
    },
    telemetry: options.telemetry ?? { storage_latency_ms: 0 },
    error: structuredError(options.code ?? "STORAGE_ERROR", message, {
      retryable: options.retryable ?? true,
    }),
  };
}
