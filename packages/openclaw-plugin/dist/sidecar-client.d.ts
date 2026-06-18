import { EventEmitter } from "node:events";
import type { ChildProcessWithoutNullStreams } from "node:child_process";
import { type SidecarRequest, type SidecarResponse } from "./protocol.js";
export declare class SidecarClient extends EventEmitter {
    private readonly process;
    private readonly pending;
    private readonly defaultTimeoutMs;
    private initialized;
    private readonly initConfig;
    constructor(process: ChildProcessWithoutNullStreams, options: {
        dbPath: string;
        config?: Record<string, unknown>;
        defaultTimeoutMs: number;
    });
    start(): Promise<void>;
    shutdown(): Promise<void>;
    request(request: SidecarRequest): Promise<SidecarResponse>;
    isInitialized(): boolean;
}
//# sourceMappingURL=sidecar-client.d.ts.map