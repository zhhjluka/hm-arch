/**
 * HM-Arch OpenClaw memory plugin entrypoint.
 *
 * Full recall/capture/sidecar behavior is implemented incrementally; this
 * package is installable and exposes the memory slot contract for OpenClaw.
 */

const PLUGIN_ID = "memory-hm-arch";

function asBool(value, fallback) {
  return typeof value === "boolean" ? value : fallback;
}

function asInt(value, fallback) {
  return Number.isInteger(value) ? value : fallback;
}

export default function register(api) {
  const config = api.pluginConfig ?? {};
  const topK = asInt(config.topK, 5);
  const maxContextChars = asInt(config.maxContextChars, 4000);
  const autoRecall = asBool(config.autoRecall, true);
  const autoCapture = asBool(config.autoCapture, true);

  if (typeof api.registerMemoryPromptSection === "function") {
    api.registerMemoryPromptSection(async () => {
      if (!autoRecall) {
        return "";
      }
      return "";
    });
  }

  if (typeof api.registerMemoryFlushPlan === "function" && autoCapture) {
    api.registerMemoryFlushPlan(async () => ({ mode: "noop" }));
  }

  if (typeof api.registerTool === "function") {
    api.registerTool({
      name: "memory_recall",
      description: "Recall durable HM-Arch memories for the active session",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          query: { type: "string" },
          topK: { type: "integer", minimum: 1 },
        },
      },
      execute: async () => ({ memories: [], topK, maxContextChars }),
    });
    api.registerTool({
      name: "memory_store",
      description: "Store a durable HM-Arch memory",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          content: { type: "string" },
        },
        required: ["content"],
      },
      execute: async () => ({ stored: false, plugin: PLUGIN_ID }),
    });
    api.registerTool({
      name: "memory_forget",
      description: "Forget a durable HM-Arch memory by id",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {
          memoryId: { type: "string" },
        },
        required: ["memoryId"],
      },
      execute: async () => ({ forgotten: false, plugin: PLUGIN_ID }),
    });
  }
}
