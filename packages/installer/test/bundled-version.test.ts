import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { readBundledHmArchVersion } from "../src/bundled-version.js";

describe("bundled hm-arch version", () => {
  it("reads __version__ from the monorepo", () => {
    const version = readBundledHmArchVersion();
    assert.match(version, /^\d+\.\d+\.\d+$/);
  });
});
