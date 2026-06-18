import { randomUUID } from "node:crypto";

import {
  CURRENT_PROTOCOL_VERSION,
  parseSidecarResponseLine,
  type SidecarOperation,
  type SidecarRequest,
  type SidecarResponse,
} from "./sidecar-protocol.js";

export type SidecarTransport = {
  write(line: string): void;
  onData(handler: (chunk: string) => void): void;
  onClose(handler: (code: number | null) => void): void;
  close(): Promise<void>;
};

type PendingRequest = {
  resolve: (response: SidecarResponse) => void;
  reject: (error: Error) => void;
  timer: NodeJS.Timeout;
};

export class SidecarClient {
  private readonly pending = new Map<string, PendingRequest>();
  private buffer = "";
  private closed = false;

  constructor(private readonly transport: SidecarTransport) {
    transport.onData((chunk) => this.handleChunk(chunk));
    transport.onClose(() => this.rejectAll(new Error("sidecar transport closed")));
  }

  async request(
    operation: SidecarOperation,
    params: Record<string, unknown>,
    options: { timeoutMs: number },
  ): Promise<SidecarResponse> {
    if (this.closed) {
      throw new Error("sidecar client is closed");
    }
    const correlationId = randomUUID();
    const request: SidecarRequest = {
      protocol_version: CURRENT_PROTOCOL_VERSION,
      correlation_id: correlationId,
      operation,
      params,
      timeout_ms: options.timeoutMs,
    };
    const line = `${JSON.stringify(request)}\n`;
    return await new Promise<SidecarResponse>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(correlationId);
        reject(new Error(`sidecar ${operation} timed out after ${options.timeoutMs}ms`));
      }, options.timeoutMs);
      this.pending.set(correlationId, { resolve, reject, timer });
      this.transport.write(line);
    });
  }

  async close(): Promise<void> {
    if (this.closed) {
      return;
    }
    this.closed = true;
    this.rejectAll(new Error("sidecar client closed"));
    await this.transport.close();
  }

  private handleChunk(chunk: string): void {
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
      } catch (error) {
        this.rejectAll(
          error instanceof Error ? error : new Error(`invalid sidecar response: ${String(error)}`),
        );
      }
    }
  }

  private rejectAll(error: Error): void {
    for (const [id, pending] of this.pending.entries()) {
      clearTimeout(pending.timer);
      pending.reject(error);
      this.pending.delete(id);
    }
  }
}
