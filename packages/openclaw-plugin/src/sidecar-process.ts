import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";

import { SidecarClient } from "./sidecar-client.js";

export type SidecarProcessOptions = {
  command: string[];
  dbPath: string;
  config?: Record<string, unknown>;
  requestTimeoutMs: number;
  maxRestartAttempts?: number;
  baseBackoffMs?: number;
};

export class SidecarProcessManager {
  private client: SidecarClient | null = null;
  private child: ChildProcessWithoutNullStreams | null = null;
  private restartAttempts = 0;
  private readonly maxRestartAttempts: number;
  private readonly baseBackoffMs: number;
  private startPromise: Promise<SidecarClient> | null = null;

  constructor(private readonly options: SidecarProcessOptions) {
    this.maxRestartAttempts = options.maxRestartAttempts ?? 5;
    this.baseBackoffMs = options.baseBackoffMs ?? 250;
  }

  async getClient(): Promise<SidecarClient> {
    if (this.client?.isInitialized()) {
      return this.client;
    }
    if (!this.startPromise) {
      this.startPromise = this.startFresh().finally(() => {
        this.startPromise = null;
      });
    }
    return this.startPromise;
  }

  async stop(): Promise<void> {
    if (this.client) {
      try {
        await this.client.shutdown();
      } catch {
        // Best-effort shutdown before terminating the process.
      }
    }
    if (this.child && !this.child.killed) {
      this.child.kill("SIGTERM");
    }
    this.client = null;
    this.child = null;
    this.restartAttempts = 0;
  }

  private async startFresh(): Promise<SidecarClient> {
    while (this.restartAttempts <= this.maxRestartAttempts) {
      try {
        const child = this.spawnProcess();
        const client = new SidecarClient(child, {
          dbPath: this.options.dbPath,
          config: this.options.config,
          defaultTimeoutMs: this.options.requestTimeoutMs,
        });
        client.on("exit", () => {
          this.client = null;
          this.child = null;
        });
        await client.start();
        this.child = child;
        this.client = client;
        this.restartAttempts = 0;
        return client;
      } catch (error) {
        this.restartAttempts += 1;
        if (this.restartAttempts > this.maxRestartAttempts) {
          throw error;
        }
        await sleep(this.baseBackoffMs * 2 ** (this.restartAttempts - 1));
      }
    }
    throw new Error("unable to start HM-Arch sidecar");
  }

  private spawnProcess(): ChildProcessWithoutNullStreams {
    const [command, ...args] = this.options.command;
    if (!command) {
      throw new Error("sidecar command is empty");
    }
    return spawn(command, args, {
      stdio: ["pipe", "pipe", "pipe"],
      env: process.env,
    }) as ChildProcessWithoutNullStreams;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
