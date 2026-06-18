import { TurnCaptureTracker } from "./capture.js";
import { readPluginConfig, resolveDbPath, resolveRequestTimeoutMs, resolveSidecarCommand, } from "./config.js";
import { registerHooks, registerPromptSection } from "./hooks.js";
import { SidecarProcessManager } from "./sidecar-process.js";
import { createMemoryTools } from "./tools.js";
export const PLUGIN_ID = "memory-hm-arch";
export function register(api) {
    const pluginConfig = readPluginConfig(api);
    const dbPath = resolveDbPath(pluginConfig);
    const manager = new SidecarProcessManager({
        command: resolveSidecarCommand(pluginConfig),
        dbPath,
        config: {
            preset: "code_agent",
            topK: pluginConfig.topK,
            maxContextChars: pluginConfig.maxContextChars,
        },
        requestTimeoutMs: resolveRequestTimeoutMs(pluginConfig),
    });
    const tracker = new TurnCaptureTracker();
    for (const tool of createMemoryTools(manager, pluginConfig)) {
        api.registerTool(tool, { names: [tool.name], optional: true });
    }
    registerHooks(api, manager, pluginConfig, tracker);
    registerPromptSection(api);
    const lifecycle = api.lifecycle?.registerRuntimeLifecycle;
    if (typeof lifecycle === "function") {
        lifecycle({
            id: PLUGIN_ID,
            onShutdown: async () => {
                await manager.stop();
            },
        });
    }
}
export { SidecarClient, } from "./sidecar-client.js";
export { SidecarProcessManager, } from "./sidecar-process.js";
export { buildRequest, parseResponseLine, } from "./protocol.js";
export { TurnCaptureTracker, extractLatestTurn, extractPromptText, } from "./capture.js";
export { fingerprintTurn, readPluginConfig, resolveDbPath, resolveSidecarCommand, } from "./config.js";
//# sourceMappingURL=index.js.map