import type { OpenClawPluginApi } from "./types.js";
export declare const PLUGIN_ID = "memory-hm-arch";
export declare function register(api: OpenClawPluginApi): void;
export { SidecarClient, } from "./sidecar-client.js";
export { SidecarProcessManager, } from "./sidecar-process.js";
export { buildRequest, parseResponseLine, } from "./protocol.js";
export { TurnCaptureTracker, extractLatestTurn, extractPromptText, } from "./capture.js";
export { fingerprintTurn, readPluginConfig, resolveDbPath, resolveSidecarCommand, } from "./config.js";
//# sourceMappingURL=index.d.ts.map