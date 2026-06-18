import { type SidecarOperation, type SidecarResponse } from "./sidecar-protocol.js";
export type SidecarTransport = {
    write(line: string): void;
    onData(handler: (chunk: string) => void): void;
    onClose(handler: (code: number | null) => void): void;
    close(): Promise<void>;
};
export declare class SidecarClient {
    private readonly transport;
    private readonly pending;
    private buffer;
    private closed;
    constructor(transport: SidecarTransport);
    request(operation: SidecarOperation, params: Record<string, unknown>, options: {
        timeoutMs: number;
    }): Promise<SidecarResponse>;
    close(): Promise<void>;
    private handleChunk;
    private rejectAll;
}
//# sourceMappingURL=sidecar-client.d.ts.map