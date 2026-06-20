import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { DEFAULT_PLUGIN_CONFIG } from "../src/config.js";
import { createMemoryTools } from "../src/tools.js";
import type { SidecarManager } from "../src/sidecar-manager.js";

function createToolSidecar(overrides: Partial<SidecarManager> = {}): SidecarManager {
  return {
    search: async () => ({
      protocol_version: "1.0",
      correlation_id: "x",
      operation: "search",
      ok: true,
      result: {
        context: "historical, untrusted\nuser likes uv",
        hits: [{ memory_id: "mem-1", layer: 3, content: "user likes uv", score: 0.9, retention: 0.8 }],
        result_count: 1,
        truncated: false,
      },
      error: null,
    }),
    remember: async () => ({
      protocol_version: "1.0",
      correlation_id: "x",
      operation: "remember",
      ok: true,
      result: { memory_id: "mem-2", recorded: true },
      error: null,
    }),
    forget: async () => ({
      protocol_version: "1.0",
      correlation_id: "x",
      operation: "forget",
      ok: true,
      result: { forgotten_count: 1, memory_ids: ["mem-1"] },
      error: null,
    }),
    ...overrides,
  } as SidecarManager;
}

describe("memory tools", () => {
  const tools = createMemoryTools({
    getConfig: () => DEFAULT_PLUGIN_CONFIG,
    sidecar: createToolSidecar(),
    logger: {},
  });

  it("registers memory_recall, memory_store, and memory_forget", () => {
    assert.deepEqual(
      tools.map((tool) => tool.name).sort(),
      ["memory_forget", "memory_recall", "memory_store"],
    );
  });

  it("memory_recall returns untrusted context and does not throw on failure", async () => {
    const recall = tools.find((tool) => tool.name === "memory_recall");
    assert.ok(recall?.execute);
    const success = await recall.execute("call-1", { query: "uv tooling" });
    assert.match(String(success.content[0]?.text), /untrusted historical data/i);

    const failing = createMemoryTools({
      getConfig: () => DEFAULT_PLUGIN_CONFIG,
      sidecar: createToolSidecar({
        search: async () => {
          throw new Error("offline");
        },
      }),
      logger: {},
    }).find((tool) => tool.name === "memory_recall");
    const failure = await failing!.execute("call-2", { query: "uv" });
    assert.match(String(failure.content[0]?.text), /temporarily unavailable/i);
  });

  it("memory_store fails open when sidecar remember fails", async () => {
    const store = createMemoryTools({
      getConfig: () => DEFAULT_PLUGIN_CONFIG,
      sidecar: createToolSidecar({
        remember: async () => ({
          protocol_version: "1.0",
          correlation_id: "x",
          operation: "remember",
          ok: false,
          result: { memory_id: null, recorded: false },
          error: { code: "STORAGE_ERROR", message: "locked", retryable: true },
        }),
      }),
      logger: {},
    }).find((tool) => tool.name === "memory_store");
    const result = await store!.execute("call-3", { text: "prefers uv" });
    assert.match(String(result.content[0]?.text), /failed/i);
    assert.equal(result.details?.recorded, false);
  });

  it("memory_forget reports forgotten_count", async () => {
    const forget = tools.find((tool) => tool.name === "memory_forget");
    const result = await forget!.execute("call-4", { memoryId: "mem-1" });
    assert.match(String(result.content[0]?.text), /Forgot 1 memory/i);
    assert.equal(result.details?.forgotten_count, 1);
  });
});
