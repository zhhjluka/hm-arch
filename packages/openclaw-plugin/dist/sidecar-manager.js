import { spawn } from "node:child_process";
import { once } from "node:events";
import { SidecarClient } from "./sidecar-client.js";
import { CURRENT_PROTOCOL_VERSION, } from "./sidecar-protocol.js";
class ProcessTransport {
    child;
    constructor(child) {
        this.child = child;
    }
    write(line) {
        this.child.stdin.write(line);
    }
    onData(handler) {
        this.child.stdout.on("data", (chunk) => {
            handler(typeof chunk === "string" ? chunk : chunk.toString("utf8"));
        });
    }
    onClose(handler) {
        this.child.on("close", (code) => handler(code));
        this.child.on("error", () => handler(null));
    }
    async close() {
        if (!this.child.killed) {
            this.child.stdin.end();
            this.child.kill();
        }
        await Promise.race([
            once(this.child, "close"),
            new Promise((resolve) => setTimeout(resolve, 50)),
        ]);
    }
}
export class SidecarManager {
    options;
    client = null;
    child = null;
    started = false;
    stopping = false;
    restartAttempts = 0;
    startupPromise = null;
    spawnFn;
    constructor(options) {
        this.options = options;
        this.spawnFn = options.spawn ?? spawn;
    }
    async start() {
        if (this.started) {
            return;
        }
        this.started = true;
        this.stopping = false;
        await this.ensureClient();
    }
    async stop() {
        this.stopping = true;
        this.started = false;
        this.startupPromise = null;
        if (this.client) {
            try {
                await this.request("shutdown", {}, { timeoutMs: this.options.requestTimeoutMs });
            }
            catch {
                // Best-effort shutdown; process teardown still runs below.
            }
            await this.client.close();
            this.client = null;
        }
        await this.tearDownProcess();
    }
    async request(operation, params, options) {
        const timeoutMs = options?.timeoutMs ?? this.options.requestTimeoutMs;
        try {
            const client = await this.ensureClient();
            return await client.request(operation, params, { timeoutMs });
        }
        catch (error) {
            if (!this.stopping) {
                this.options.logger?.warn?.(`memory-hm-arch: sidecar ${operation} failed: ${String(error)}`);
            }
            throw error;
        }
    }
    async search(params) {
        return await this.request("search", {
            query: params.query,
            top_k: params.topK,
            max_context_chars: params.maxContextChars,
            ...(params.sessionId ? { session_id: params.sessionId } : {}),
        }, { timeoutMs: this.options.requestTimeoutMs });
    }
    async remember(params) {
        return await this.request("remember", {
            content: params.content,
            ...(params.sessionId ? { session_id: params.sessionId } : {}),
            ...(params.importance !== undefined ? { importance: params.importance } : {}),
            ...(params.eventType ? { event_type: params.eventType } : {}),
            ...(params.metadata ? { metadata: params.metadata } : {}),
        }, { timeoutMs: this.options.requestTimeoutMs });
    }
    async forget(params) {
        return await this.request("forget", {
            ...(params.memoryIds ? { memory_ids: params.memoryIds } : {}),
            ...(params.query ? { query: params.query } : {}),
        }, { timeoutMs: this.options.requestTimeoutMs });
    }
    async recordTurn(params) {
        return await this.request("record_turn", {
            ...(params.userMessage ? { user_message: params.userMessage } : {}),
            ...(params.agentMessage ? { agent_message: params.agentMessage } : {}),
            ...(params.sessionId ? { session_id: params.sessionId } : {}),
        }, { timeoutMs: this.options.requestTimeoutMs });
    }
    async consolidate(params) {
        return await this.request("consolidate", {
            ...(params.force !== undefined ? { force: params.force } : {}),
            ...(params.sessionId ? { session_id: params.sessionId } : {}),
        }, { timeoutMs: Math.max(this.options.requestTimeoutMs, 60_000) });
    }
    async ensureClient() {
        if (this.client) {
            return this.client;
        }
        if (!this.startupPromise) {
            this.startupPromise = this.spawnProcess().finally(() => {
                this.startupPromise = null;
            });
        }
        try {
            await this.startupPromise;
        }
        catch (error) {
            await this.tearDownProcess();
            throw error;
        }
        if (!this.client) {
            throw new Error("sidecar client failed to initialize");
        }
        return this.client;
    }
    async tearDownProcess() {
        if (this.client) {
            try {
                await this.client.close();
            }
            catch {
                // Best-effort client teardown.
            }
            this.client = null;
        }
        if (this.child && !this.child.killed) {
            this.child.kill();
            await Promise.race([
                once(this.child, "close"),
                new Promise((resolve) => setTimeout(resolve, 50)),
            ]);
        }
        this.child = null;
    }
    async spawnProcess() {
        await this.tearDownProcess();
        const [command, ...args] = this.options.command;
        if (!command) {
            throw new Error("sidecar command is empty");
        }
        const child = this.spawnFn(command, args, { stdio: ["pipe", "pipe", "pipe"] });
        this.child = child;
        const transport = new ProcessTransport(child);
        const client = new SidecarClient(transport);
        this.client = client;
        child.stderr.on("data", (chunk) => {
            const text = typeof chunk === "string" ? chunk : chunk.toString("utf8");
            const trimmed = text.trim();
            if (trimmed) {
                this.options.logger?.info?.(`memory-hm-arch sidecar: ${trimmed}`);
            }
        });
        child.on("close", (code) => {
            if (this.stopping) {
                return;
            }
            this.client = null;
            this.child = null;
            this.startupPromise = null;
            this.options.logger?.warn?.(`memory-hm-arch: sidecar exited with code ${String(code)}; scheduling restart`);
            void this.scheduleRestart();
        });
        try {
            const initResponse = await client.request("initialize", {
                db_path: this.options.dbPath,
                client_capabilities: ["telemetry.v1", "forget.by_query.v1", "health.deep.v1"],
            }, { timeoutMs: this.options.startupTimeoutMs });
            if (!initResponse.ok) {
                throw new Error(initResponse.error?.message ?? "sidecar initialize failed");
            }
            const negotiated = initResponse.result.negotiated_protocol_version;
            if (typeof negotiated === "string" && negotiated !== CURRENT_PROTOCOL_VERSION) {
                this.options.logger?.info?.(`memory-hm-arch: negotiated sidecar protocol ${negotiated}`);
            }
            this.restartAttempts = 0;
        }
        catch (error) {
            await this.tearDownProcess();
            throw error;
        }
    }
    async scheduleRestart() {
        if (!this.started || this.stopping) {
            return;
        }
        this.restartAttempts += 1;
        const backoff = Math.min(250 * 2 ** (this.restartAttempts - 1), this.options.maxRestartBackoffMs);
        await new Promise((resolve) => setTimeout(resolve, backoff));
        if (!this.started || this.stopping) {
            return;
        }
        try {
            if (!this.startupPromise) {
                this.startupPromise = this.spawnProcess().finally(() => {
                    this.startupPromise = null;
                });
            }
            await this.startupPromise;
        }
        catch (error) {
            this.options.logger?.warn?.(`memory-hm-arch: sidecar restart failed: ${String(error)}`);
            void this.scheduleRestart();
        }
    }
}
//# sourceMappingURL=sidecar-manager.js.map