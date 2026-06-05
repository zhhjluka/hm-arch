import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

import { readBundledHmArchVersion } from "../src/bundled-version.js";
import { readInstallerVersion } from "../src/installer-version.js";

const REPO_VERSION_FILE = join(import.meta.dirname, "..", "..", "..", "src", "hm_arch", "_version.py");
const GENERATED_BUNDLED_FILE = join(import.meta.dirname, "..", "src", "bundled-version.json");

describe("bundled hm-arch version", () => {
  it("reads version from generated bundled-version.json", () => {
    const version = readBundledHmArchVersion();
    assert.match(version, /^\d+\.\d+\.\d+$/);
  });

  it("matches monorepo __version__ at build time", () => {
    const monorepoText = readFileSync(REPO_VERSION_FILE, "utf8");
    const match = /__version__\s*=\s*["']([^"']+)["']/.exec(monorepoText);
    assert.ok(match, "monorepo version file should define __version__");
    const generated = JSON.parse(readFileSync(GENERATED_BUNDLED_FILE, "utf8")) as { version: string };
    assert.equal(readBundledHmArchVersion(), generated.version);
    assert.equal(readBundledHmArchVersion(), match[1]);
  });

  it("reads installer version from generated installer-version.json", () => {
    const packageJson = JSON.parse(
      readFileSync(join(import.meta.dirname, "..", "package.json"), "utf8"),
    ) as { version: string };
    const generated = JSON.parse(
      readFileSync(join(import.meta.dirname, "..", "src", "installer-version.json"), "utf8"),
    ) as { version: string };
    assert.equal(readInstallerVersion(), generated.version);
    assert.equal(readInstallerVersion(), packageJson.version);
  });
});
