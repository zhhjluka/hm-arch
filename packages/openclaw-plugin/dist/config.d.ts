import type { OpenClawPluginApi, PluginConfig } from "./types.js";
export declare function readPluginConfig(api: OpenClawPluginApi): PluginConfig;
export declare function resolveDbPath(pluginConfig: PluginConfig, openclawRoot?: string): string;
export declare function resolveSidecarCommand(pluginConfig: PluginConfig): string[];
export declare function resolveTopK(pluginConfig: PluginConfig): number;
export declare function resolveMaxContextChars(pluginConfig: PluginConfig): number;
export declare function resolveRequestTimeoutMs(pluginConfig: PluginConfig): number;
export declare function fingerprintTurn(sessionId: string, userMessage: string, agentMessage: string): string;
//# sourceMappingURL=config.d.ts.map