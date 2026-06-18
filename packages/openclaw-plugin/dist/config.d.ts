export declare const HM_ARCH_PLUGIN_ID = "memory-hm-arch";
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
export declare const DEFAULT_PLUGIN_CONFIG: PluginConfig;
export declare function resolvePluginConfig(pluginConfig: Record<string, unknown> | undefined, resolvePath: (input: string) => string): PluginConfig;
export declare function pluginConfigSchema(): {
    type: string;
    additionalProperties: boolean;
    properties: {
        dbPath: {
            type: string;
        };
        sidecarCommand: {
            type: string;
            items: {
                type: string;
            };
        };
        autoRecall: {
            type: string;
        };
        autoCapture: {
            type: string;
        };
        topK: {
            type: string;
            minimum: number;
        };
        maxContextChars: {
            type: string;
            minimum: number;
        };
        consolidateOnSessionEnd: {
            type: string;
        };
        requestTimeoutMs: {
            type: string;
            minimum: number;
        };
        startupTimeoutMs: {
            type: string;
            minimum: number;
        };
        maxRestartBackoffMs: {
            type: string;
            minimum: number;
        };
    };
};
//# sourceMappingURL=config.d.ts.map