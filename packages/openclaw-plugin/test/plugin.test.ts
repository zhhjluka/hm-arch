import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";

import pluginEntry from "../src/index.js";
import { HM_ARCH_PLUGIN_ID } from "../src/config.js";
import { hasMemorySlotConflict, isActiveMemoryPlugin } from "../src/slot.js";

const packageRoot = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("plugin entry", () => {
  it("exports a memory plugin with the expected id", () => {
    assert.equal(pluginEntry.id, HM_ARCH_PLUGIN_ID);
    assert.equal(pluginEntry.kind, "memory");
    assert.equal(typeof pluginEntry.register, "function");
  });

  it("manifest declares memory tools and schema", () => {
    const manifest = JSON.parse(
      readFileSync(join(packageRoot, "openclaw.plugin.json"), "utf8"),
    ) as {
      id: string;
      kind: string;
      contracts: { tools: string[] };
      configSchema: { properties: Record<string, unknown> };
    };
    assert.equal(manifest.id, HM_ARCH_PLUGIN_ID);
    assert.equal(manifest.kind, "memory");
    assert.deepEqual(manifest.contracts.tools.sort(), [
      "memory_forget",
      "memory_recall",
      "memory_store",
    ]);
    assert.ok(manifest.configSchema.properties.dbPath);
    assert.ok(manifest.configSchema.properties.autoRecall);
    assert.ok(manifest.configSchema.properties.consolidateOnSessionEnd);
  });

  it("detects memory slot conflicts without mutating unrelated config", () => {
    const conflictConfig = {
      plugins: {
        slots: { memory: "memory-lancedb" },
        entries: {
          "memory-lancedb": { enabled: true, config: { dbPath: "other.db" } },
          [HM_ARCH_PLUGIN_ID]: { enabled: true, config: { dbPath: "hm.db" } },
        },
      },
    };
    assert.equal(hasMemorySlotConflict(conflictConfig), true);
    assert.equal(isActiveMemoryPlugin(conflictConfig), false);
    assert.equal(conflictConfig.plugins.entries["memory-lancedb"].config.dbPath, "other.db");
  });
});
