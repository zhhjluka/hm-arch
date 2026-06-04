import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { postinstall } from "../src/postinstall.js";

const packageRoot = join(dirname(fileURLToPath(import.meta.url)), "..");

describe("postinstall", () => {
  it("exported hook is a no-op and does not throw", () => {
    assert.doesNotThrow(() => postinstall());
  });

  it("npm lifecycle script is an empty no-op file", () => {
    const script = readFileSync(join(packageRoot, "scripts", "postinstall.mjs"), "utf8");
    assert.match(script, /intentional no-op/i);
    assert.doesNotMatch(script, /install\s*\(/);
    assert.doesNotMatch(script, /hooks\.json/);
  });
});
