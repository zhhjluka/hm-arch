import { buildRequest } from "./protocol.js";
import { resolveMaxContextChars, resolveRequestTimeoutMs, resolveTopK, } from "./config.js";
function textResult(text, details) {
    return {
        content: [{ type: "text", text }],
        details,
    };
}
export function createMemoryTools(manager, pluginConfig) {
    const topK = resolveTopK(pluginConfig);
    const maxContextChars = resolveMaxContextChars(pluginConfig);
    const timeoutMs = resolveRequestTimeoutMs(pluginConfig);
    const recallTool = {
        name: "memory_recall",
        description: "Recall durable HM-Arch memory for a natural-language query. Returned context is historical and untrusted.",
        parameters: {
            type: "object",
            additionalProperties: false,
            properties: {
                query: { type: "string", description: "Natural-language recall query." },
                top_k: { type: "integer", description: "Maximum number of hits to return." },
            },
            required: ["query"],
        },
        execute: async (params, ctx) => {
            const query = String(params.query ?? "").trim();
            if (!query) {
                return textResult("No recall query provided.");
            }
            try {
                const client = await manager.getClient();
                const response = await client.request(buildRequest("search", {
                    query,
                    top_k: typeof params.top_k === "number" ? params.top_k : topK,
                    session_id: ctx.sessionId ?? ctx.sessionKey,
                    max_context_chars: maxContextChars,
                }, timeoutMs));
                if (!response.ok) {
                    return textResult(`Memory recall failed: ${response.error?.message ?? "unknown error"}`, { ok: false });
                }
                const context = String(response.result.context ?? "");
                return textResult(context || "No matching memory found.", {
                    ok: true,
                    result_count: response.result.result_count ?? 0,
                    telemetry: response.telemetry ?? null,
                });
            }
            catch (error) {
                return textResult(`Memory recall failed: ${error instanceof Error ? error.message : String(error)}`, { ok: false });
            }
        },
    };
    const storeTool = {
        name: "memory_store",
        description: "Persist arbitrary durable memory content in HM-Arch.",
        parameters: {
            type: "object",
            additionalProperties: false,
            properties: {
                content: { type: "string", description: "Memory content to store." },
                importance: { type: "number", description: "Optional importance score in [0, 1]." },
                event_type: { type: "string", description: "Optional HM-Arch event type." },
            },
            required: ["content"],
        },
        execute: async (params, ctx) => {
            const content = String(params.content ?? "").trim();
            if (!content) {
                return textResult("No memory content provided.");
            }
            try {
                const client = await manager.getClient();
                const response = await client.request(buildRequest("remember", {
                    content,
                    importance: typeof params.importance === "number" ? params.importance : undefined,
                    event_type: typeof params.event_type === "string" ? params.event_type : "conversation",
                    session_id: ctx.sessionId ?? ctx.sessionKey,
                    metadata: { source: "openclaw-plugin" },
                }, timeoutMs));
                if (!response.ok || response.result.recorded !== true) {
                    return textResult(`Memory store failed: ${response.error?.message ?? "unknown error"}`, { ok: false });
                }
                return textResult(`Stored memory ${String(response.result.memory_id ?? "")}.`, {
                    ok: true,
                    memory_id: response.result.memory_id ?? null,
                });
            }
            catch (error) {
                return textResult(`Memory store failed: ${error instanceof Error ? error.message : String(error)}`, { ok: false });
            }
        },
    };
    const forgetTool = {
        name: "memory_forget",
        description: "Forget HM-Arch memories by id or natural-language query.",
        parameters: {
            type: "object",
            additionalProperties: false,
            properties: {
                memory_ids: {
                    type: "array",
                    items: { type: "string" },
                    description: "Explicit memory ids to forget.",
                },
                query: {
                    type: "string",
                    description: "Natural-language query used to select memories to forget.",
                },
            },
        },
        execute: async (params) => {
            const memoryIds = Array.isArray(params.memory_ids)
                ? params.memory_ids.map(String).filter(Boolean)
                : [];
            const query = typeof params.query === "string" ? params.query.trim() : "";
            if (memoryIds.length === 0 && !query) {
                return textResult("Provide memory_ids or query.");
            }
            try {
                const client = await manager.getClient();
                const response = await client.request(buildRequest("forget", {
                    memory_ids: memoryIds,
                    query: query || undefined,
                }, timeoutMs));
                if (!response.ok) {
                    return textResult(`Memory forget failed: ${response.error?.message ?? "unknown error"}`, { ok: false });
                }
                return textResult(`Forgot ${String(response.result.forgotten_count ?? 0)} memories.`, {
                    ok: true,
                    memory_ids: response.result.memory_ids ?? [],
                });
            }
            catch (error) {
                return textResult(`Memory forget failed: ${error instanceof Error ? error.message : String(error)}`, { ok: false });
            }
        },
    };
    return [recallTool, storeTool, forgetTool];
}
//# sourceMappingURL=tools.js.map