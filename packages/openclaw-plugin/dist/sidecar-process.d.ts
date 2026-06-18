import { SidecarClient } from "./sidecar-client.js";
export type SidecarProcessOptions = {
    command: string[];
    dbPath: string;
    config?: Record<string, unknown>;
    requestTimeoutMs: number;
    maxRestartAttempts?: number;
    baseBackoffMs?: number;
};
export declare class SidecarProcessManager {
    private readonly options;
    private client;
    private child;
    private restartAttempts;
    private readonly maxRestartAttempts;
    private readonly baseBackoffMs;
    private startPromise;
    constructor(options: SidecarProcessOptions);
    getClient(): Promise<SidecarClient>;
    stop(): Promise<void>;
    private startFresh;
    private spawnProcess;
}
//# sourceMappingURL=sidecar-process.d.ts.map