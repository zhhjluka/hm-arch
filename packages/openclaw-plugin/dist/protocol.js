export const CURRENT_PROTOCOL_VERSION = "1.0";
let correlationCounter = 0;
export function nextCorrelationId(prefix = "oc") {
    correlationCounter += 1;
    return `${prefix}-${Date.now()}-${correlationCounter}`;
}
export function buildRequest(operation, params, timeoutMs) {
    const request = {
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
export function serializeRequest(request) {
    return `${JSON.stringify(request)}\n`;
}
export function parseResponseLine(line) {
    const payload = JSON.parse(line);
    if (!payload || typeof payload !== "object") {
        throw new Error("sidecar response must be a JSON object");
    }
    return payload;
}
//# sourceMappingURL=protocol.js.map