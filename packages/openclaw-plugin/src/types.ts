export type PluginConfig = {
  dbPath?: string;
  sidecarCommand?: string[];
  autoRecall?: boolean;
  autoCapture?: boolean;
  topK?: number;
  maxContextChars?: number;
  consolidateOnSessionEnd?: boolean;
  requestTimeoutMs?: number;
};

export const DEFAULT_TOP_K = 5;
export const DEFAULT_MAX_CONTEXT_CHARS = 4000;
export const DEFAULT_REQUEST_TIMEOUT_MS = 30_000;
export const DEFAULT_DB_FILENAME = "hm_arch_memory.db";

export type OpenClawPluginApi = {
  config?: Record<string, unknown>;
  pluginConfig?: PluginConfig;
  registerTool: (
    tool: AgentTool,
    opts?: { names?: string[]; optional?: boolean },
  ) => void;
  registerHook: (
    events: string | string[],
    handler: HookHandler,
    opts?: { catchErrors?: boolean },
  ) => void;
  on?: (event: string, handler: HookHandler) => void;
  registerMemoryPromptSection?: (
    builder: (params: {
      availableTools: Set<string>;
      citationsMode?: string;
    }) => string[],
  ) => void;
  lifecycle?: {
    registerRuntimeLifecycle?: (registration: {
      id: string;
      onShutdown?: () => Promise<void> | void;
    }) => void;
  };
};

export type AgentTool = {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  execute: (params: Record<string, unknown>, ctx: ToolContext) => Promise<ToolResult>;
};

export type ToolContext = {
  sessionId?: string;
  sessionKey?: string;
};

export type ToolResult = {
  content: Array<{ type: "text"; text: string }>;
  details?: Record<string, unknown>;
};

export type HookHandler = (
  event: Record<string, unknown>,
  ctx: Record<string, unknown>,
) => Promise<Record<string, unknown> | void> | Record<string, unknown> | void;

export type PromptBuildEvent = {
  prompt?: string;
  userMessage?: string;
  messages?: Array<{ role?: string; content?: string }>;
};

export type AgentEndEvent = {
  sessionId?: string;
  sessionKey?: string;
  userMessage?: string;
  agentMessage?: string;
  messages?: Array<{ role?: string; content?: string }>;
  turnId?: string;
};

export type SessionEndEvent = {
  sessionId?: string;
  sessionKey?: string;
};
