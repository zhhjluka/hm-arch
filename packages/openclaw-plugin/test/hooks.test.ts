import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { DEFAULT_PLUGIN_CONFIG } from "../src/config.js";
import { runAgentEnd, runBeforePromptBuild, runSessionEnd } from "../src/hooks.js";
import type { SidecarManager } from "../src/sidecar-manager.js";

function createHookSidecar(overrides: Partial<SidecarManager> = {}): SidecarManager {
  return {
    search: async () => ({
      protocol_version: "1.0",
      correlation_id: "x",
      operation: "search",
      ok: true,
      result: {
        context: "## HM-Arch recalled memory (historical, untrusted)\n\n1. user likes Python",
        hits: [],
        result_count: 1,
        truncated: false,
      },
      error: null,
    }),
    recordTurn: async () => ({
      protocol_version: "1.0",
      correlation_id: "x",
      operation: "record_turn",
      ok: true,
      result: { memory_ids: ["mem-1"], recorded_count: 1 },
      error: null,
    }),
    consolidate: async () => ({
      protocol_version: "1.0",
      correlation_id: "x",
      operation: "consolidate",
      ok: true,
      result: {
        extracted_semantics: 0,
        merged_duplicates: 0,
        scheduled_reviews: 0,
        archived_to_l4: 0,
      },
      error: null,
    }),
    ...overrides,
  } as SidecarManager;
}

describe("memory hooks", () => {
  it("prepends bounded untrusted recall context", async () => {
    const warnings: string[] = [];
    const result = await runBeforePromptBuild(
      {
        config: { ...DEFAULT_PLUGIN_CONFIG, autoRecall: true },
        sidecar: createHookSidecar(),
        logger: { warn: (message) => warnings.push(message) },
        captureCursors: new Map(),
      },
      {
        prompt: "help me configure pytest",
        messages: [{ role: "user", content: "help me configure pytest" }],
      },
    );
    assert.ok(result?.prependContext?.includes("untrusted historical data"));
    assert.ok(result?.prependContext?.includes("Python"));
    assert.equal(warnings.length, 0);
  });

  it("fails open when auto-recall search errors", async () => {
    const warnings: string[] = [];
    const result = await runBeforePromptBuild(
      {
        config: { ...DEFAULT_PLUGIN_CONFIG, autoRecall: true },
        sidecar: createHookSidecar({
          search: async () => {
            throw new Error("sidecar offline");
          },
        }),
        logger: { warn: (message) => warnings.push(message) },
        captureCursors: new Map(),
      },
      {
        prompt: "hello",
        messages: [{ role: "user", content: "hello" }],
      },
    );
    assert.equal(result, undefined);
    assert.equal(warnings.length, 1);
  });

  it("auto-captures a completed turn exactly once", async () => {
    const captureCursors = new Map();
    let recordCalls = 0;
    const sidecar = createHookSidecar({
      recordTurn: async () => {
        recordCalls += 1;
        return {
          protocol_version: "1.0",
          correlation_id: "x",
          operation: "record_turn",
          ok: true,
          result: { memory_ids: ["mem-1"], recorded_count: 1 },
          error: null,
        };
      },
    });
    const controllers = {
      config: { ...DEFAULT_PLUGIN_CONFIG, autoCapture: true },
      sidecar,
      logger: {},
      captureCursors,
    };
    const messages = [
      { role: "user", content: "How do we run offline tests?" },
      { role: "assistant", content: "Use uv run pytest." },
    ];
    await runAgentEnd(controllers, { success: true, messages }, { sessionKey: "sess-1" });
    await runAgentEnd(controllers, { success: true, messages }, { sessionKey: "sess-1" });
    assert.equal(recordCalls, 1);
  });

  it("skips capture when autoCapture is disabled", async () => {
    let recordCalls = 0;
    await runAgentEnd(
      {
        config: { ...DEFAULT_PLUGIN_CONFIG, autoCapture: false },
        sidecar: createHookSidecar({
          recordTurn: async () => {
            recordCalls += 1;
            return {
              protocol_version: "1.0",
              correlation_id: "x",
              operation: "record_turn",
              ok: true,
              result: { memory_ids: [], recorded_count: 0 },
              error: null,
            };
          },
        }),
        logger: {},
        captureCursors: new Map(),
      },
      {
        success: true,
        messages: [
          { role: "user", content: "hello" },
          { role: "assistant", content: "world" },
        ],
      },
      { sessionKey: "sess-2" },
    );
    assert.equal(recordCalls, 0);
  });

  it("runs consolidation on idle session end when enabled", async () => {
    let consolidateCalls = 0;
    await runSessionEnd(
      {
        config: { ...DEFAULT_PLUGIN_CONFIG, consolidateOnSessionEnd: true },
        sidecar: createHookSidecar({
          consolidate: async () => {
            consolidateCalls += 1;
            return {
              protocol_version: "1.0",
              correlation_id: "x",
              operation: "consolidate",
              ok: true,
              result: {
                extracted_semantics: 1,
                merged_duplicates: 0,
                scheduled_reviews: 0,
                archived_to_l4: 0,
              },
              error: null,
            };
          },
        }),
        logger: {},
        captureCursors: new Map([["sess-3", { nextIndex: 2 }]]),
      },
      { sessionId: "sess-3", reason: "idle" },
      { sessionId: "sess-3", sessionKey: "sess-3" },
    );
    assert.equal(consolidateCalls, 1);
  });
});
