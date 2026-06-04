import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { main } from "../src/cli.js";

describe("hm-arch-install CLI", () => {
  it("exits 2 for unknown flags on status", () => {
    assert.equal(main(["status", "--bogus"]), 2);
  });

  it("exits 2 for unknown flags on install", () => {
    assert.equal(main(["install", "codex", "--bogus"]), 2);
  });
});
