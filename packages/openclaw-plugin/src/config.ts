export const HM_ARCH_PLUGIN_ID = "memory-hm-arch";

export type PluginConfig = {
  dbPath: string;
  sidecarCommand: string[];
  autoRecall: boolean;
  autoCapture: boolean;
  topK: number;
  maxContextChars: number;
  consolidateOnSessionEnd: boolean;
  requestTimeoutMs: number;
  startupTimeoutMs: number;
  maxRestartBackoffMs: number;
};

export const DEFAULT_PLUGIN_CONFIG: PluginConfig = {
  dbPath: "hm_arch_memory.db",
  sidecarCommand: ["hm-arch", "openclaw", "sidecar"],
  autoRecall: true,
  autoCapture: true,
  topK: 5,
  maxContextChars: 4000,
  consolidateOnSessionEnd: false,
  requestTimeoutMs: 15_000,
  startupTimeoutMs: 30_000,
  maxRestartBackoffMs: 30_000,
};

function readString(value: unknown, fallback: string): string {
  if (typeof value !== "string") {
    return fallback;
  }
  const trimmed = value.trim();
  return trimmed || fallback;
}

function readBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function readPositiveInt(value: unknown, fallback: number): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 1) {
    return fallback;
  }
  return value;
}

function readStringArray(value: unknown, fallback: string[]): string[] {
  if (!Array.isArray(value) || value.length === 0) {
    return [...fallback];
  }
  const parts = value
    .map((item) => (typeof item === "string" ? item.trim() : ""))
    .filter(Boolean);
  return parts.length > 0 ? parts : [...fallback];
}

export function resolvePluginConfig(
  pluginConfig: Record<string, unknown> | undefined,
  resolvePath: (input: string) => string,
): PluginConfig {
  const raw = pluginConfig ?? {};
  const dbPath = resolvePath(readString(raw.dbPath, DEFAULT_PLUGIN_CONFIG.dbPath));
  return {
    dbPath,
    sidecarCommand: readStringArray(raw.sidecarCommand, DEFAULT_PLUGIN_CONFIG.sidecarCommand),
    autoRecall: readBoolean(raw.autoRecall, DEFAULT_PLUGIN_CONFIG.autoRecall),
    autoCapture: readBoolean(raw.autoCapture, DEFAULT_PLUGIN_CONFIG.autoCapture),
    topK: readPositiveInt(raw.topK, DEFAULT_PLUGIN_CONFIG.topK),
    maxContextChars: readPositiveInt(
      raw.maxContextChars,
      DEFAULT_PLUGIN_CONFIG.maxContextChars,
    ),
    consolidateOnSessionEnd: readBoolean(
      raw.consolidateOnSessionEnd,
      DEFAULT_PLUGIN_CONFIG.consolidateOnSessionEnd,
    ),
    requestTimeoutMs: readPositiveInt(
      raw.requestTimeoutMs,
      DEFAULT_PLUGIN_CONFIG.requestTimeoutMs,
    ),
    startupTimeoutMs: readPositiveInt(
      raw.startupTimeoutMs,
      DEFAULT_PLUGIN_CONFIG.startupTimeoutMs,
    ),
    maxRestartBackoffMs: readPositiveInt(
      raw.maxRestartBackoffMs,
      DEFAULT_PLUGIN_CONFIG.maxRestartBackoffMs,
    ),
  };
}

export function pluginConfigSchema() {
  return {
    type: "object",
    additionalProperties: false,
    properties: {
      dbPath: { type: "string" },
      sidecarCommand: {
        type: "array",
        items: { type: "string" },
      },
      autoRecall: { type: "boolean" },
      autoCapture: { type: "boolean" },
      topK: { type: "integer", minimum: 1 },
      maxContextChars: { type: "integer", minimum: 1 },
      consolidateOnSessionEnd: { type: "boolean" },
      requestTimeoutMs: { type: "integer", minimum: 1 },
      startupTimeoutMs: { type: "integer", minimum: 1 },
      maxRestartBackoffMs: { type: "integer", minimum: 1 },
    },
  };
}
