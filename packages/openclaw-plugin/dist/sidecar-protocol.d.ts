/**
 * JSONL stdio sidecar protocol types and validators for OpenClaw plugin mocks.
 *
 * Contract: docs/sidecar-protocol.md
 * Golden fixtures: fixtures/sidecar-protocol/
 */
export declare const CURRENT_PROTOCOL_VERSION = "1.0";
export declare const SUPPORTED_OPERATIONS: readonly ["initialize", "health", "search", "remember", "forget", "record_turn", "consolidate", "shutdown"];
export type SidecarOperation = (typeof SUPPORTED_OPERATIONS)[number];
export declare const FAIL_OPEN_OPERATIONS: readonly SidecarOperation[];
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
export declare class ProtocolValidationError extends Error {
    constructor(message: string);
}
export declare function validateProtocolVersion(version: string, serverVersion?: string): void;
export declare function negotiateProtocolVersion(clientVersion: string, serverVersion?: string): string;
export declare function negotiateCapabilities(clientCapabilities: readonly string[], serverCapabilities?: readonly string[]): {
    serverCapabilities: string[];
    negotiatedCapabilities: string[];
};
export declare function validateOperation(value: unknown): SidecarOperation;
export declare function parseSidecarRequest(data: unknown): SidecarRequest;
export declare function parseSidecarResponse(data: unknown): SidecarResponse;
export declare function parseSidecarRequestLine(line: string): SidecarRequest;
export declare function parseSidecarResponseLine(line: string): SidecarResponse;
export declare function structuredError(code: string, message: string, options: {
    retryable: boolean;
    details?: Record<string, unknown>;
}): StructuredError;
export declare function failOpenSearch(correlationId: string, message: string, options?: {
    protocolVersion?: string;
    code?: string;
    retryable?: boolean;
    telemetry?: SidecarTelemetry;
}): SidecarResponse;
export declare function failOpenRemember(correlationId: string, message: string, options?: {
    protocolVersion?: string;
    code?: string;
    retryable?: boolean;
    telemetry?: SidecarTelemetry;
}): SidecarResponse;
export declare function failOpenRecordTurn(correlationId: string, message: string, options?: {
    protocolVersion?: string;
    code?: string;
    retryable?: boolean;
    telemetry?: SidecarTelemetry;
}): SidecarResponse;
//# sourceMappingURL=sidecar-protocol.d.ts.map