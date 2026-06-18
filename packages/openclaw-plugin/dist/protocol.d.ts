export declare const CURRENT_PROTOCOL_VERSION = "1.0";
export type SidecarOperation = "initialize" | "health" | "search" | "remember" | "forget" | "record_turn" | "consolidate" | "shutdown";
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
export declare function nextCorrelationId(prefix?: string): string;
export declare function buildRequest(operation: SidecarOperation, params: Record<string, unknown>, timeoutMs?: number): SidecarRequest;
export declare function serializeRequest(request: SidecarRequest): string;
export declare function parseResponseLine(line: string): SidecarResponse;
//# sourceMappingURL=protocol.d.ts.map