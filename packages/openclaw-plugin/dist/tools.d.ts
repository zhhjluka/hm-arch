import type { AnyAgentTool } from "openclaw/plugin-sdk/plugin-entry";
import type { PluginConfig } from "./config.js";
import type { SidecarManager } from "./sidecar-manager.js";
type ToolLogger = {
    warn?: (message: string) => void;
};
export declare function createMemoryTools(options: {
    getConfig: () => PluginConfig;
    sidecar: SidecarManager | {
        readonly current: SidecarManager;
    };
    logger: ToolLogger;
}): AnyAgentTool[];
export {};
//# sourceMappingURL=tools.d.ts.map