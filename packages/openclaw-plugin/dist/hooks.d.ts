import type { PluginLogger } from "openclaw/plugin-sdk/plugin-entry";
import type { PluginConfig } from "./config.js";
import { type AutoCaptureCursor } from "./messages.js";
import type { SidecarManager } from "./sidecar-manager.js";
export type HookLogger = Pick<PluginLogger, "info" | "warn">;
export type HookContext = {
    sessionKey?: string;
    sessionId?: string;
};
export type HookControllers = {
    config: PluginConfig;
    sidecar: SidecarManager;
    logger: HookLogger;
    captureCursors: Map<string, AutoCaptureCursor>;
};
export declare function runBeforePromptBuild(controllers: HookControllers, event: {
    prompt: string;
    messages: unknown[];
}): Promise<{
    prependContext?: string;
} | undefined>;
export declare function runAgentEnd(controllers: HookControllers, event: {
    success: boolean;
    messages: unknown[];
}, ctx: HookContext): Promise<void>;
export declare function runSessionEnd(controllers: HookControllers, event: {
    sessionId: string;
    sessionKey?: string;
    reason?: string;
    nextSessionId?: string;
    nextSessionKey?: string;
}, ctx: HookContext): Promise<void>;
//# sourceMappingURL=hooks.d.ts.map