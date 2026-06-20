import assert from "node:assert/strict";
import type { ChildProcessWithoutNullStreams } from "node:child_process";
import { spawn } from "node:child_process";
import { describe, it } from "node:test";

import { DEFAULT_PLUGIN_CONFIG } from "../src/config.js";
import { runAgentEnd, runBeforePromptBuild, runSessionEnd } from "../src/hooks.js";
import { SidecarManager } from "../src/sidecar-manager.js";
import { createMemoryTools } from "../src/tools.js";
import { createE2EContext, hasPythonSidecarSupport } from "./e2e-helpers.js";

const e2e = hasPythonSidecarSupport() ? describe : describe.skip;

function createManager(
  ctx: ReturnType<typeof createE2EContext>,
  options: {
    onSpawn?: (child: ChildProcessWithoutNullStreams) => void;
    config?: Partial<typeof DEFAULT_PLUGIN_CONFIG>;
  } = {},
): SidecarManager {
  const config = { ...ctx.config, ...options.config };
  return new SidecarManager({
    command: config.sidecarCommand,
    dbPath: config.dbPath,
    requestTimeoutMs: config.requestTimeoutMs,
    startupTimeoutMs: config.startupTimeoutMs,
    maxRestartBackoffMs: config.maxRestartBackoffMs,
    ...(options.onSpawn
      ? {
          spawn: (command: string, args: string[], spawnOptions) => {
            const child = spawn(command, args, spawnOptions);
            options.onSpawn?.(child);
            return child;
          },
        }
      : {}),
  });
}

e2e("OpenClaw plugin E2E (real Python sidecar)", () => {
  it("stores, restarts sidecar, and recalls persisted memory", async () => {
    const ctx = createE2EContext();
    const marker = "e2e persistent recall marker after gateway restart";
    try {
      const first = createManager(ctx);
      await first.start();
      const remember = await first.remember({
        content: marker,
        importance: 0.9,
        metadata: { source: "openclaw-e2e" },
      });
      assert.equal(remember.ok, true);
      assert.equal(remember.result.recorded, true);
      await first.stop();

      const second = createManager(ctx);
      await second.start();
      const search = await second.search({
        query: "persistent recall marker",
        topK: 5,
        maxContextChars: 4000,
      });
      await second.stop();

      assert.equal(search.ok, true);
      assert.ok((search.result.result_count as number) >= 1);
      const hits = Array.isArray(search.result.hits) ? search.result.hits : [];
      assert.ok(
        hits.some((hit) => String(hit.content ?? "").includes(marker)) ||
          String(search.result.context ?? "").includes(marker),
      );
      const telemetry = search.telemetry as Record<string, unknown> | undefined;
      assert.ok(telemetry);
      assert.ok((telemetry.query_latency_ms as number) >= 0);
      assert.ok((telemetry.returned_tokens as number) >= 0);
      assert.ok((telemetry.returned_characters as number) >= 0);
    } finally {
      ctx.cleanup();
    }
  });

  it("auto-recalls before prompt build and fails open on search errors", async () => {
    const ctx = createE2EContext();
    const sidecar = createManager(ctx);
    const hungSidecar = createManager(ctx, {
      config: {
        sidecarCommand: ["node", "-e", "setInterval(()=>{}, 1_000_000)"],
        startupTimeoutMs: 500,
        requestTimeoutMs: 200,
      },
    });
    try {
      await sidecar.start();
      await sidecar.remember({
        content: "user prefers uv for offline pytest workflows",
        importance: 0.85,
      });

      const recall = await runBeforePromptBuild(
        {
          config: { ...ctx.config, autoRecall: true },
          sidecar,
          logger: {},
          captureCursors: new Map(),
        },
        {
          prompt: "configure pytest offline",
          messages: [{ role: "user", content: "configure pytest offline" }],
        },
      );
      assert.ok(recall?.prependContext?.includes("untrusted historical data"));
      assert.ok(recall?.prependContext?.toLowerCase().includes("uv"));

      const warnings: string[] = [];
      const failOpen = await runBeforePromptBuild(
        {
          config: { ...ctx.config, autoRecall: true },
          sidecar: hungSidecar,
          logger: { warn: (message) => warnings.push(message) },
          captureCursors: new Map(),
        },
        {
          prompt: "hello",
          messages: [{ role: "user", content: "hello" }],
        },
      );
      assert.equal(failOpen, undefined);
      assert.equal(warnings.length, 1);
    } finally {
      await sidecar.stop();
      await hungSidecar.stop();
      ctx.cleanup();
    }
  });

  it("auto-captures a completed turn exactly once", async () => {
    const ctx = createE2EContext();
    try {
      const sidecar = createManager(ctx);
      await sidecar.start();
      const captureCursors = new Map();
      const controllers = {
        config: { ...ctx.config, autoCapture: true },
        sidecar,
        logger: {},
        captureCursors,
      };
      const messages = [
        { role: "user", content: "How do we run offline OpenClaw E2E tests?" },
        { role: "assistant", content: "Use the isolated OPENCLAW_STATE_DIR fixture." },
      ];
      await runAgentEnd(controllers, { success: true, messages }, { sessionKey: "sess-e2e" });
      await runAgentEnd(controllers, { success: true, messages }, { sessionKey: "sess-e2e" });

      const search = await sidecar.search({
        query: "offline OpenClaw E2E",
        topK: 5,
        maxContextChars: 4000,
      });
      await sidecar.stop();
      assert.equal(search.ok, true);
      assert.ok((search.result.result_count as number) >= 1);
    } finally {
      ctx.cleanup();
    }
  });

  it("runs session-end consolidation when enabled", async () => {
    const ctx = createE2EContext({ consolidateOnSessionEnd: true });
    try {
      const sidecar = createManager(ctx);
      await sidecar.start();
      await sidecar.remember({
        content: "session consolidation seed for OpenClaw E2E",
        importance: 0.7,
      });
      await runSessionEnd(
        {
          config: ctx.config,
          sidecar,
          logger: {},
          captureCursors: new Map([["sess-consolidate", { nextIndex: 1 }]]),
        },
        { sessionId: "sess-consolidate", reason: "idle" },
        { sessionId: "sess-consolidate", sessionKey: "sess-consolidate" },
      );
      const health = await sidecar.request("health", { deep: true });
      await sidecar.stop();
      assert.equal(health.ok, true);
      assert.equal(health.result.db_reachable, true);
    } finally {
      ctx.cleanup();
    }
  });

  it("exposes memory_recall, memory_store, and memory_forget tools", async () => {
    const ctx = createE2EContext();
    try {
      const sidecar = createManager(ctx);
      await sidecar.start();
      const tools = createMemoryTools({
        getConfig: () => ctx.config,
        sidecar,
        logger: {},
      });
      const store = tools.find((tool) => tool.name === "memory_store");
      const recall = tools.find((tool) => tool.name === "memory_recall");
      const forget = tools.find((tool) => tool.name === "memory_forget");
      assert.ok(store?.execute);
      assert.ok(recall?.execute);
      assert.ok(forget?.execute);

      const stored = await store.execute("tool-store", {
        text: "OpenClaw E2E tool store marker",
        importance: 0.8,
      });
      assert.match(String(stored.content[0]?.text), /Stored memory/i);
      assert.equal(stored.details?.recorded, true);
      const memoryId = stored.details?.memory_id;
      assert.ok(typeof memoryId === "string");

      const recalled = await recall.execute("tool-recall", {
        query: "OpenClaw E2E tool store",
      });
      assert.match(String(recalled.content[0]?.text), /untrusted historical data/i);

      const forgotten = await forget.execute("tool-forget", {
        query: "OpenClaw E2E tool store marker",
      });
      assert.equal(typeof forgotten.details?.forgotten_count, "number");
      assert.ok(String(forgotten.content[0]?.text).length > 0);
      await sidecar.stop();
    } finally {
      ctx.cleanup();
    }
  });

  it("recovers after sidecar crash and bounded client timeout", async () => {
    const ctx = createE2EContext({ maxRestartBackoffMs: 500 });
    let spawnedChild: ChildProcessWithoutNullStreams | null = null;
    const sidecar = createManager(ctx, {
      onSpawn: (child) => {
        spawnedChild = child;
      },
    });
    const hung = createManager(ctx, {
      config: {
        sidecarCommand: ["node", "-e", "process.stdin.on('data',()=>{})"],
        startupTimeoutMs: 200,
        requestTimeoutMs: 200,
      },
    });
    try {
      await sidecar.start();
      await sidecar.remember({
        content: "sidecar crash recovery marker",
        importance: 0.9,
      });
      assert.ok(spawnedChild);
      spawnedChild.kill("SIGKILL");
      await new Promise((resolve) => setTimeout(resolve, 1_200));

      const search = await sidecar.search({
        query: "crash recovery marker",
        topK: 5,
        maxContextChars: 4000,
      });
      assert.equal(search.ok, true);
      assert.ok((search.result.result_count as number) >= 1);

      await assert.rejects(
        () => hung.start(),
        /timed out|initialize failed|failed/i,
      );
    } finally {
      await sidecar.stop();
      await hung.stop();
      ctx.cleanup();
    }
  });
});
