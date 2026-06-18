export const CURRENT_PROTOCOL_VERSION = "1.0";

export type SidecarOperation =
  | "initialize"
  | "health"
  | "search"
  | "remember"
  | "forget"
  | "record_turn"
  | "consolidate"
  | "shutdown";

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
  telemetry?: Record<string, number> | null;
  error?: {
    code: string;
    message: string;
    retryable: boolean;
    details?: Record<string, unknown>;
  } | null;
};

let correlationCounter = 0;

export function nextCorrelationId(prefix = "oc"): string {
  correlationCounter += 1;
  return `${prefix}-${Date.now()}-${correlationCounter}`;
}

export function buildRequest(
  operation: SidecarOperation,
  params: Record<string, unknown>,
  timeoutMs?: number,
): SidecarRequest {
  const request: SidecarRequest = {
    protocol_version: CURRENT_PROTOCOL_VERSION,
    correlation_id: nextCorrelationId(),
    operation,
    params,
  };
  if (timeoutMs !== undefined) {
    request.timeout_ms = timeoutMs;
  }
  return request;
}

export function serializeRequest(request: SidecarRequest): string {
  return `${JSON.stringify(request)}\n`;
}

export function parseResponseLine(line: string): SidecarResponse {
  const payload = JSON.parse(line) as SidecarResponse;
  if (!payload || typeof payload !== "object") {
    throw new Error("sidecar response must be a JSON object");
  }
  return payload;
}
