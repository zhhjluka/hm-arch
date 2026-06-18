import { randomUUID } from "node:crypto";
import { CURRENT_PROTOCOL_VERSION, parseSidecarResponseLine, } from "./sidecar-protocol.js";
export class SidecarClient {
    transport;
    pending = new Map();
    buffer = "";
    closed = false;
    constructor(transport) {
        this.transport = transport;
        transport.onData((chunk) => this.handleChunk(chunk));
        transport.onClose(() => this.rejectAll(new Error("sidecar transport closed")));
    }
    async request(operation, params, options) {
        if (this.closed) {
            throw new Error("sidecar client is closed");
        }
        const correlationId = randomUUID();
        const request = {
            protocol_version: CURRENT_PROTOCOL_VERSION,
            correlation_id: correlationId,
            operation,
            params,
            timeout_ms: options.timeoutMs,
        };
        const line = `${JSON.stringify(request)}\n`;
        return await new Promise((resolve, reject) => {
            const timer = setTimeout(() => {
                this.pending.delete(correlationId);
                reject(new Error(`sidecar ${operation} timed out after ${options.timeoutMs}ms`));
            }, options.timeoutMs);
            this.pending.set(correlationId, { resolve, reject, timer });
            this.transport.write(line);
        });
    }
    async close() {
        if (this.closed) {
            return;
        }
        this.closed = true;
        this.rejectAll(new Error("sidecar client closed"));
        await this.transport.close();
    }
    handleChunk(chunk) {
        this.buffer += chunk;
        while (true) {
            const newline = this.buffer.indexOf("\n");
            if (newline < 0) {
                return;
            }
            const line = this.buffer.slice(0, newline).trim();
            this.buffer = this.buffer.slice(newline + 1);
            if (!line) {
                continue;
            }
            try {
                const response = parseSidecarResponseLine(line);
                const pending = this.pending.get(response.correlation_id);
                if (!pending) {
                    continue;
                }
                clearTimeout(pending.timer);
                this.pending.delete(response.correlation_id);
                pending.resolve(response);
            }
            catch (error) {
                this.rejectAll(error instanceof Error ? error : new Error(`invalid sidecar response: ${String(error)}`));
            }
        }
    }
    rejectAll(error) {
        for (const [id, pending] of this.pending.entries()) {
            clearTimeout(pending.timer);
            pending.reject(error);
            this.pending.delete(id);
        }
    }
}
//# sourceMappingURL=sidecar-client.js.map