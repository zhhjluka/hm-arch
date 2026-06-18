import { spawn } from "node:child_process";
import { SidecarClient } from "./sidecar-client.js";
export class SidecarProcessManager {
    options;
    client = null;
    child = null;
    restartAttempts = 0;
    maxRestartAttempts;
    baseBackoffMs;
    startPromise = null;
    constructor(options) {
        this.options = options;
        this.maxRestartAttempts = options.maxRestartAttempts ?? 5;
        this.baseBackoffMs = options.baseBackoffMs ?? 250;
    }
    async getClient() {
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
    async stop() {
        if (this.client) {
            try {
                await this.client.shutdown();
            }
            catch {
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
    async startFresh() {
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
            }
            catch (error) {
                this.restartAttempts += 1;
                if (this.restartAttempts > this.maxRestartAttempts) {
                    throw error;
                }
                await sleep(this.baseBackoffMs * 2 ** (this.restartAttempts - 1));
            }
        }
        throw new Error("unable to start HM-Arch sidecar");
    }
    spawnProcess() {
        const [command, ...args] = this.options.command;
        if (!command) {
            throw new Error("sidecar command is empty");
        }
        return spawn(command, args, {
            stdio: ["pipe", "pipe", "pipe"],
            env: process.env,
        });
    }
}
function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}
//# sourceMappingURL=sidecar-process.js.map