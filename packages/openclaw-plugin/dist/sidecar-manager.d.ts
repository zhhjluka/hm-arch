import { type ChildProcessWithoutNullStreams } from "node:child_process";
import { type SidecarOperation, type SidecarResponse } from "./sidecar-protocol.js";
export type SpawnFn = (command: string, args: string[], options: {
    stdio: ["pipe", "pipe", "pipe"];
}) => ChildProcessWithoutNullStreams;
export type SidecarManagerOptions = {
    command: string[];
    dbPath: string;
    requestTimeoutMs: number;
    startupTimeoutMs: number;
    maxRestartBackoffMs: number;
    spawn?: SpawnFn;
    logger?: {
        info?: (message: string) => void;
        warn?: (message: string) => void;
    };
};
export declare class SidecarManager {
    private readonly options;
    private client;
    private child;
    private started;
    private stopping;
    private restartAttempts;
    private startupPromise;
    private readonly spawnFn;
    constructor(options: SidecarManagerOptions);
    start(): Promise<void>;
    stop(): Promise<void>;
    request(operation: SidecarOperation, params: Record<string, unknown>, options?: {
        timeoutMs?: number;
    }): Promise<SidecarResponse>;
    search(params: {
        query: string;
        topK: number;
        maxContextChars: number;
        sessionId?: string;
    }): Promise<SidecarResponse>;
    remember(params: {
        content: string;
        sessionId?: string;
        importance?: number;
        eventType?: string;
        metadata?: Record<string, unknown>;
    }): Promise<SidecarResponse>;
    forget(params: {
        memoryIds?: string[];
        query?: string;
    }): Promise<SidecarResponse>;
    recordTurn(params: {
        userMessage?: string;
        agentMessage?: string;
        sessionId?: string;
    }): Promise<SidecarResponse>;
    consolidate(params: {
        force?: boolean;
        sessionId?: string;
    }): Promise<SidecarResponse>;
    private ensureClient;
    private tearDownProcess;
    private spawnProcess;
    private scheduleRestart;
}
//# sourceMappingURL=sidecar-manager.d.ts.map