import type { AnyAgentTool } from "openclaw/plugin-sdk/plugin-entry";

import type { PluginConfig } from "./config.js";
import { formatRecallContext, normalizeRecallQuery } from "./messages.js";
import type { SidecarManager } from "./sidecar-manager.js";

type ToolLogger = {
  warn?: (message: string) => void;
};

export function createMemoryTools(options: {
  getConfig: () => PluginConfig;
  sidecar: SidecarManager | { readonly current: SidecarManager };
  logger: ToolLogger;
}): AnyAgentTool[] {
  const getSidecar = () =>
    "current" in options.sidecar ? options.sidecar.current : options.sidecar;
  const recallTool: AnyAgentTool = {
    name: "memory_recall",
    label: "Memory Recall",
    description:
      "Search HM-Arch durable memory for relevant facts, preferences, and prior decisions.",
    parameters: {
      type: "object",
      properties: {
        query: { type: "string", description: "Natural-language recall query." },
        limit: { type: "integer", description: "Maximum hits to return (default topK)." },
      },
      required: ["query"],
    },
    async execute(_toolCallId, params) {
      const raw = params as Record<string, unknown>;
      const query = typeof raw.query === "string" ? raw.query.trim() : "";
      if (!query) {
        return {
          content: [{ type: "text", text: "memory_recall requires a non-empty query." }],
          details: { count: 0 },
        };
      }
      const config = options.getConfig();
      const limit =
        typeof raw.limit === "number" && Number.isInteger(raw.limit) && raw.limit > 0
          ? raw.limit
          : config.topK;
      try {
        const response = await getSidecar().search({
          query: normalizeRecallQuery(query, config.maxContextChars),
          topK: limit,
          maxContextChars: config.maxContextChars,
        });
        if (!response.ok) {
          options.logger.warn?.(
            `memory-hm-arch: memory_recall failed: ${response.error?.message ?? "unknown error"}`,
          );
          return {
            content: [
              {
                type: "text",
                text: "Memory is temporarily unavailable. Continue without recalled context.",
              },
            ],
            details: { count: 0, unavailable: true },
          };
        }
        const context =
          typeof response.result.context === "string" ? response.result.context : "";
        const hits = Array.isArray(response.result.hits) ? response.result.hits : [];
        if (!context && hits.length === 0) {
          return {
            content: [{ type: "text", text: "No relevant memories found." }],
            details: { count: 0 },
          };
        }
        const formatted = formatRecallContext(context);
        return {
          content: [{ type: "text", text: formatted || "No relevant memories found." }],
          details: {
            count: typeof response.result.result_count === "number"
              ? response.result.result_count
              : hits.length,
            hits,
            truncated: response.result.truncated === true,
          },
        };
      } catch (error) {
        options.logger.warn?.(`memory-hm-arch: memory_recall failed: ${String(error)}`);
        return {
          content: [
            {
              type: "text",
              text: "Memory is temporarily unavailable. Continue without recalled context.",
            },
          ],
          details: { count: 0, unavailable: true },
        };
      }
    },
  };

  const storeTool: AnyAgentTool = {
    name: "memory_store",
    label: "Memory Store",
    description: "Store an explicit fact or preference in HM-Arch durable memory.",
    parameters: {
      type: "object",
      properties: {
        text: { type: "string", description: "Fact or preference to remember." },
        content: { type: "string", description: "Alias for text." },
        importance: {
          type: "number",
          description: "Importance score in [0, 1] (default 0.7).",
        },
      },
      required: [],
    },
    async execute(_toolCallId, params) {
      const raw = params as Record<string, unknown>;
      const content =
        (typeof raw.text === "string" ? raw.text : "") ||
        (typeof raw.content === "string" ? raw.content : "");
      const trimmed = content.trim();
      if (!trimmed) {
        return {
          content: [{ type: "text", text: "memory_store requires non-empty text or content." }],
          details: { recorded: false },
        };
      }
      const importance =
        typeof raw.importance === "number" && raw.importance >= 0 && raw.importance <= 1
          ? raw.importance
          : 0.7;
      try {
        const response = await getSidecar().remember({
          content: trimmed,
          importance,
          eventType: "conversation",
          metadata: { source: "openclaw-plugin" },
        });
        if (!response.ok || response.result.recorded !== true) {
          options.logger.warn?.(
            `memory-hm-arch: memory_store failed: ${response.error?.message ?? "unknown error"}`,
          );
          return {
            content: [{ type: "text", text: "Memory store failed; continuing without persistence." }],
            details: { recorded: false },
          };
        }
        return {
          content: [{ type: "text", text: `Stored memory: "${trimmed.slice(0, 120)}"` }],
          details: {
            recorded: true,
            memory_id: response.result.memory_id,
          },
        };
      } catch (error) {
        options.logger.warn?.(`memory-hm-arch: memory_store failed: ${String(error)}`);
        return {
          content: [{ type: "text", text: "Memory store failed; continuing without persistence." }],
          details: { recorded: false },
        };
      }
    },
  };

  const forgetTool: AnyAgentTool = {
    name: "memory_forget",
    label: "Memory Forget",
    description: "Forget memories by id or semantic query.",
    parameters: {
      type: "object",
      properties: {
        query: { type: "string", description: "Semantic query to find memories to forget." },
        memoryId: { type: "string", description: "Specific memory id to forget." },
        memory_id: { type: "string", description: "Alias for memoryId." },
      },
      required: [],
    },
    async execute(_toolCallId, params) {
      const raw = params as Record<string, unknown>;
      const memoryId =
        (typeof raw.memoryId === "string" ? raw.memoryId : "") ||
        (typeof raw.memory_id === "string" ? raw.memory_id : "");
      const query = typeof raw.query === "string" ? raw.query.trim() : "";
      if (!memoryId && !query) {
        return {
          content: [{ type: "text", text: "Provide memoryId or query." }],
          details: { forgotten_count: 0 },
        };
      }
      try {
        const response = await getSidecar().forget({
          ...(memoryId ? { memoryIds: [memoryId] } : {}),
          ...(query ? { query } : {}),
        });
        if (!response.ok) {
          return {
            content: [
              {
                type: "text",
                text: `Forget failed: ${response.error?.message ?? "unknown error"}`,
              },
            ],
            details: { forgotten_count: 0 },
          };
        }
        const forgotten =
          typeof response.result.forgotten_count === "number"
            ? response.result.forgotten_count
            : 0;
        const ids = Array.isArray(response.result.memory_ids)
          ? response.result.memory_ids
          : [];
        return {
          content: [
            {
              type: "text",
              text:
                forgotten > 0
                  ? `Forgot ${forgotten} memor${forgotten === 1 ? "y" : "ies"}.`
                  : "No matching memories found.",
            },
          ],
          details: { forgotten_count: forgotten, memory_ids: ids },
        };
      } catch (error) {
        options.logger.warn?.(`memory-hm-arch: memory_forget failed: ${String(error)}`);
        return {
          content: [{ type: "text", text: `Forget failed: ${String(error)}` }],
          details: { forgotten_count: 0 },
        };
      }
    },
  };

  return [recallTool, storeTool, forgetTool];
}
