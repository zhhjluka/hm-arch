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
];
export const FAIL_OPEN_OPERATIONS = [
    "search",
    "remember",
    "record_turn",
];
export class ProtocolValidationError extends Error {
    constructor(message) {
        super(message);
        this.name = "ProtocolValidationError";
    }
}
function parseVersion(version) {
    const parts = version.split(".", 2);
    if (parts.length !== 2 ||
        !/^\d+$/.test(parts[0] ?? "") ||
        !/^\d+$/.test(parts[1] ?? "")) {
        throw new ProtocolValidationError(`protocol_version must be MAJOR.MINOR, got ${JSON.stringify(version)}`);
    }
    return [Number(parts[0]), Number(parts[1])];
}
export function validateProtocolVersion(version, serverVersion = CURRENT_PROTOCOL_VERSION) {
    const client = parseVersion(version);
    const server = parseVersion(serverVersion);
    if (client[0] !== server[0]) {
        throw new ProtocolValidationError(`Incompatible protocol major version ${JSON.stringify(version)}; server is ${JSON.stringify(serverVersion)}`);
    }
}
export function negotiateProtocolVersion(clientVersion, serverVersion = CURRENT_PROTOCOL_VERSION) {
    validateProtocolVersion(clientVersion, serverVersion);
    const client = parseVersion(clientVersion);
    const server = parseVersion(serverVersion);
    return `${client[0]}.${Math.min(client[1], server[1])}`;
}
export function negotiateCapabilities(clientCapabilities, serverCapabilities = [
    "telemetry.v1",
    "forget.by_query.v1",
    "health.deep.v1",
]) {
    const negotiated = clientCapabilities.filter((tag) => serverCapabilities.includes(tag));
    return {
        serverCapabilities: [...serverCapabilities],
        negotiatedCapabilities: negotiated,
    };
}
export function validateOperation(value) {
    if (typeof value !== "string") {
        throw new ProtocolValidationError("operation must be a string");
    }
    const normalized = value.trim().toLowerCase();
    if (!SUPPORTED_OPERATIONS.includes(normalized)) {
        throw new ProtocolValidationError(`Unsupported operation ${JSON.stringify(value)}. Supported operations: ${SUPPORTED_OPERATIONS.join(", ")}`);
    }
    return normalized;
}
function requireObject(value, label) {
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
        throw new ProtocolValidationError(`${label} must be a JSON object`);
    }
    return value;
}
function requireString(value, key) {
    if (typeof value !== "string") {
        throw new ProtocolValidationError(`${key} must be a string`);
    }
    const stripped = value.trim();
    if (!stripped) {
        throw new ProtocolValidationError(`${key} must be a non-empty string`);
    }
    return stripped;
}
function optionalString(data, key) {
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
function optionalInt(data, key) {
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
function requireBool(data, key) {
    if (!(key in data)) {
        throw new ProtocolValidationError(`${key} is required`);
    }
    const value = data[key];
    if (typeof value !== "boolean") {
        throw new ProtocolValidationError(`${key} must be a boolean`);
    }
    return value;
}
function requireInt(data, key) {
    if (!(key in data)) {
        throw new ProtocolValidationError(`${key} is required`);
    }
    const value = data[key];
    if (typeof value === "boolean") {
        throw new ProtocolValidationError(`${key} must be an integer`);
    }
    if (typeof value !== "number" || !Number.isInteger(value)) {
        throw new ProtocolValidationError(`${key} must be an integer`);
    }
    return value;
}
function requireFloat(data, key) {
    if (!(key in data)) {
        throw new ProtocolValidationError(`${key} is required`);
    }
    const value = data[key];
    if (typeof value === "boolean") {
        throw new ProtocolValidationError(`${key} must be a number`);
    }
    if (typeof value !== "number") {
        throw new ProtocolValidationError(`${key} must be a number`);
    }
    return value;
}
function requireStringValue(data, key) {
    if (!(key in data)) {
        throw new ProtocolValidationError(`${key} is required`);
    }
    const value = data[key];
    if (typeof value !== "string") {
        throw new ProtocolValidationError(`${key} must be a string`);
    }
    return value;
}
function requireOperation(data) {
    if (!("operation" in data)) {
        throw new ProtocolValidationError("operation is required");
    }
    return validateOperation(data.operation);
}
function optionalStringList(data, key) {
    if (!(key in data)) {
        return [];
    }
    const value = data[key];
    if (value === null || value === undefined) {
        return [];
    }
    if (!Array.isArray(value)) {
        throw new ProtocolValidationError(`${key} must be an array of strings`);
    }
    return value.map((item, index) => {
        if (typeof item !== "string" || !item.trim()) {
            throw new ProtocolValidationError(`${key}[${index}] must be a non-empty string`);
        }
        return item.trim();
    });
}
function parseSearchHit(data) {
    return {
        memory_id: requireString(data.memory_id, "memory_id"),
        layer: requireInt(data, "layer"),
        content: requireStringValue(data, "content"),
        score: requireFloat(data, "score"),
        retention: requireFloat(data, "retention"),
    };
}
function parseSearchResult(result) {
    const hitsRaw = result.hits;
    if (!Array.isArray(hitsRaw)) {
        throw new ProtocolValidationError("result.hits must be an array");
    }
    return {
        context: requireStringValue(result, "context"),
        hits: hitsRaw.map((item) => parseSearchHit(requireObject(item, "hit"))),
        result_count: requireInt(result, "result_count"),
        truncated: requireBool(result, "truncated"),
    };
}
function parseRememberResult(result) {
    if (!("memory_id" in result)) {
        throw new ProtocolValidationError("result.memory_id is required");
    }
    const memoryId = result.memory_id;
    if (memoryId !== null && typeof memoryId !== "string") {
        throw new ProtocolValidationError("result.memory_id must be a string or null");
    }
    return {
        memory_id: memoryId,
        recorded: requireBool(result, "recorded"),
    };
}
function parseRecordTurnResult(result) {
    return {
        memory_ids: optionalStringList(result, "memory_ids"),
        recorded_count: requireInt(result, "recorded_count"),
    };
}
function parseSuccessResult(operation, result) {
    switch (operation) {
        case "initialize":
            return {
                ready: requireBool(result, "ready"),
                negotiated_protocol_version: requireString(result.negotiated_protocol_version, "negotiated_protocol_version"),
                server_capabilities: optionalStringList(result, "server_capabilities"),
                negotiated_capabilities: optionalStringList(result, "negotiated_capabilities"),
                db_path: requireString(result.db_path, "db_path"),
            };
        case "health":
            return {
                status: requireString(result.status, "status"),
                db_reachable: requireBool(result, "db_reachable"),
                ...(typeof result.stats === "object" &&
                    result.stats !== null &&
                    !Array.isArray(result.stats)
                    ? { stats: result.stats }
                    : {}),
            };
        case "search":
            return parseSearchResult(result);
        case "remember":
            return parseRememberResult(result);
        case "forget":
            return {
                forgotten_count: requireInt(result, "forgotten_count"),
                memory_ids: optionalStringList(result, "memory_ids"),
            };
        case "record_turn":
            return parseRecordTurnResult(result);
        case "consolidate":
            return {
                extracted_semantics: requireInt(result, "extracted_semantics"),
                merged_duplicates: requireInt(result, "merged_duplicates"),
                scheduled_reviews: requireInt(result, "scheduled_reviews"),
                archived_to_l4: requireInt(result, "archived_to_l4"),
            };
        case "shutdown":
            return { shutdown_ack: requireBool(result, "shutdown_ack") };
        default:
            throw new ProtocolValidationError(`Unsupported operation ${operation}`);
    }
}
function parseFailOpenResult(operation, result) {
    switch (operation) {
        case "search":
            return parseSearchResult(result);
        case "remember":
            return parseRememberResult(result);
        case "record_turn":
            return parseRecordTurnResult(result);
        default:
            return { ...result };
    }
}
function parseResult(operation, payload, ok) {
    const result = requireObject(payload.result ?? {}, "result");
    if (ok) {
        return parseSuccessResult(operation, result);
    }
    if (FAIL_OPEN_OPERATIONS.includes(operation)) {
        return parseFailOpenResult(operation, result);
    }
    return { ...result };
}
function parseStructuredError(data) {
    const err = requireObject(data, "error");
    return {
        code: requireString(err.code, "error.code"),
        message: requireString(err.message, "error.message"),
        retryable: typeof err.retryable === "boolean"
            ? err.retryable
            : (() => {
                throw new ProtocolValidationError("error.retryable must be a boolean");
            })(),
        ...(typeof err.details === "object" &&
            err.details !== null &&
            !Array.isArray(err.details)
            ? { details: err.details }
            : {}),
    };
}
function parseTelemetryField(data) {
    if (data === null || data === undefined) {
        return null;
    }
    const payload = requireObject(data, "telemetry");
    const telemetry = {};
    if ("query_latency_ms" in payload) {
        telemetry.query_latency_ms = requireFloat(payload, "query_latency_ms");
    }
    if ("hit_count" in payload) {
        telemetry.hit_count = requireInt(payload, "hit_count");
    }
    if ("returned_characters" in payload) {
        telemetry.returned_characters = requireInt(payload, "returned_characters");
    }
    if ("returned_tokens" in payload) {
        telemetry.returned_tokens = requireInt(payload, "returned_tokens");
    }
    if ("storage_latency_ms" in payload) {
        telemetry.storage_latency_ms = requireFloat(payload, "storage_latency_ms");
    }
    return telemetry;
}
function validateParams(operation, params) {
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
                throw new ProtocolValidationError("record_turn requires at least one non-empty user_message or agent_message");
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
export function parseSidecarRequest(data) {
    const payload = requireObject(data, "payload");
    const protocolVersion = requireString(payload.protocol_version, "protocol_version");
    validateProtocolVersion(protocolVersion);
    const correlationId = requireString(payload.correlation_id, "correlation_id");
    const operation = requireOperation(payload);
    const params = requireObject(payload.params ?? {}, "params");
    validateParams(operation, params);
    const timeoutMs = optionalInt(payload, "timeout_ms");
    if (timeoutMs !== undefined && timeoutMs < 1) {
        throw new ProtocolValidationError("timeout_ms must be >= 1");
    }
    const request = {
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
export function parseSidecarResponse(data) {
    const payload = requireObject(data, "payload");
    const protocolVersion = requireString(payload.protocol_version, "protocol_version");
    validateProtocolVersion(protocolVersion);
    const correlationId = requireString(payload.correlation_id, "correlation_id");
    const operation = requireOperation(payload);
    const ok = requireBool(payload, "ok");
    let error = null;
    if (ok) {
        if (payload.error !== null && payload.error !== undefined) {
            throw new ProtocolValidationError("successful responses must not include error");
        }
    }
    else {
        if (payload.error === null || payload.error === undefined) {
            throw new ProtocolValidationError("failed responses must include error");
        }
        error = parseStructuredError(payload.error);
    }
    const result = parseResult(operation, payload, ok);
    let telemetry;
    if (payload.telemetry === null) {
        telemetry = null;
    }
    else if (payload.telemetry !== undefined) {
        telemetry = parseTelemetryField(payload.telemetry);
    }
    return {
        protocol_version: protocolVersion,
        correlation_id: correlationId,
        operation,
        ok,
        result,
        telemetry,
        error,
    };
}
export function parseSidecarRequestLine(line) {
    const stripped = line.trim();
    if (!stripped) {
        throw new ProtocolValidationError("request line must not be empty");
    }
    return parseSidecarRequest(JSON.parse(stripped));
}
export function parseSidecarResponseLine(line) {
    const stripped = line.trim();
    if (!stripped) {
        throw new ProtocolValidationError("response line must not be empty");
    }
    return parseSidecarResponse(JSON.parse(stripped));
}
export function structuredError(code, message, options) {
    return {
        code,
        message,
        retryable: options.retryable,
        ...(options.details ? { details: options.details } : {}),
    };
}
export function failOpenSearch(correlationId, message, options = {}) {
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
export function failOpenRemember(correlationId, message, options = {}) {
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
export function failOpenRecordTurn(correlationId, message, options = {}) {
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
//# sourceMappingURL=sidecar-protocol.js.map