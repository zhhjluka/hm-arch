import { EventEmitter } from "node:events";
import { createInterface } from "node:readline";
import type { ChildProcessWithoutNullStreams } from "node:child_process";

import {
  buildRequest,
  parseResponseLine,
  serializeRequest,
  type SidecarOperation,
  type SidecarRequest,
  type SidecarResponse,
} from "./protocol.js";

type PendingRequest = {
  resolve: (response: SidecarResponse) => void;
  reject: (error: Error) => void;
  operation: SidecarOperation;
  timer?: NodeJS.Timeout;
};

export class SidecarClient extends EventEmitter {
  private readonly pending = new Map<string, PendingRequest>();
  private readonly defaultTimeoutMs: number;
  private initialized = false;
  private readonly initConfig: {
    dbPath: string;
    config: Record<string, unknown>;
    timeoutMs: number;
  };

  constructor(
    private readonly process: ChildProcessWithoutNullStreams,
    options: {
      dbPath: string;
      config?: Record<string, unknown>;
      defaultTimeoutMs: number;
    },
  ) {
    super();
    this.defaultTimeoutMs = options.defaultTimeoutMs;
    this.initConfig = {
      dbPath: options.dbPath,
      config: options.config ?? { preset: "code_agent" },
      timeoutMs: options.defaultTimeoutMs,
    };
    const stdout = createInterface({ input: this.process.stdout });
    stdout.on("line", (line) => {
      const trimmed = line.trim();
      if (!trimmed) {
        return;
      }
      try {
        const response = parseResponseLine(trimmed);
        const pending = this.pending.get(response.correlation_id);
        if (!pending) {
          return;
        }
        if (pending.timer) {
          clearTimeout(pending.timer);
        }
        this.pending.delete(response.correlation_id);
        pending.resolve(response);
      } catch (error) {
        this.emit("error", error);
      }
    });
    this.process.stderr.on("data", (chunk) => {
      this.emit("stderr", String(chunk));
    });
    this.process.on("exit", (code, signal) => {
      const message = `sidecar exited (code=${code ?? "null"}, signal=${signal ?? "null"})`;
      for (const pending of this.pending.values()) {
        if (pending.timer) {
          clearTimeout(pending.timer);
        }
        pending.reject(new Error(message));
      }
      this.pending.clear();
      this.initialized = false;
      this.emit("exit", { code, signal });
    });
  }

  async start(): Promise<void> {
    if (this.initialized) {
      return;
    }
    const response = await this.request(
      buildRequest(
        "initialize",
        {
          db_path: this.initConfig.dbPath,
          client_capabilities: ["telemetry.v1", "forget.by_query.v1"],
          config: this.initConfig.config,
        },
        this.initConfig.timeoutMs,
      ),
    );
    if (!response.ok) {
      throw new Error(response.error?.message ?? "sidecar initialize failed");
    }
    this.initialized = true;
  }

  async shutdown(): Promise<void> {
    if (!this.initialized) {
      return;
    }
    try {
      await this.request(buildRequest("shutdown", {}));
    } finally {
      this.initialized = false;
    }
  }

  async request(request: SidecarRequest): Promise<SidecarResponse> {
    return new Promise<SidecarResponse>((resolve, reject) => {
      const timeoutMs = request.timeout_ms ?? this.defaultTimeoutMs;
      const timer = setTimeout(() => {
        this.pending.delete(request.correlation_id);
        reject(new Error(`sidecar request timed out after ${timeoutMs}ms`));
      }, timeoutMs + 250);
      this.pending.set(request.correlation_id, {
        resolve,
        reject,
        operation: request.operation,
        timer,
      });
      this.process.stdin.write(serializeRequest(request));
    });
  }

  isInitialized(): boolean {
    return this.initialized;
  }
}
