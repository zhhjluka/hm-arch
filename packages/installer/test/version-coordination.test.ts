import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

import { readBundledHmArchVersion } from "../src/bundled-version.js";
import { readInstallerVersion } from "../src/installer-version.js";

const REPO_ROOT = join(import.meta.dirname, "..", "..", "..");
const VERSION_PY = join(REPO_ROOT, "src", "hm_arch", "_version.py");
const PACKAGE_JSON = join(import.meta.dirname, "..", "package.json");
const GENERATED_BUNDLED = join(import.meta.dirname, "..", "src", "bundled-version.json");
const GENERATED_INSTALLER = join(import.meta.dirname, "..", "src", "installer-version.json");

function readMonorepoVersion(): string {
  const text = readFileSync(VERSION_PY, "utf8");
  const match = /__version__\s*=\s*["']([^"']+)["']/.exec(text);
  assert.ok(match, "monorepo _version.py should define __version__");
  return match[1];
}

describe("release version coordination (MEM-64)", () => {
  it("aligns Python SSoT, bundled hm-arch, and generated JSON", () => {
    const monorepoVersion = readMonorepoVersion();
    const bundledGenerated = JSON.parse(readFileSync(GENERATED_BUNDLED, "utf8")) as {
      version: string;
    };
    assert.equal(readBundledHmArchVersion(), monorepoVersion);
    assert.equal(bundledGenerated.version, monorepoVersion);
  });

  it("aligns npm package version with generated installer-version.json", () => {
    const packageJson = JSON.parse(readFileSync(PACKAGE_JSON, "utf8")) as { version: string };
    const installerGenerated = JSON.parse(readFileSync(GENERATED_INSTALLER, "utf8")) as {
      version: string;
    };
    assert.equal(readInstallerVersion(), packageJson.version);
    assert.equal(installerGenerated.version, packageJson.version);
  });

  it("uses the same semver across npm and Python channels for coordinated releases", () => {
    const monorepoVersion = readMonorepoVersion();
    const packageJson = JSON.parse(readFileSync(PACKAGE_JSON, "utf8")) as { version: string };
    assert.equal(
      packageJson.version,
      monorepoVersion,
      "npm @hm-arch/installer version should match hm-arch __version__ for coordinated releases",
    );
  });

  it("uses valid semver strings for all coordinated versions", () => {
    const semver = /^\d+\.\d+\.\d+$/;
    assert.match(readMonorepoVersion(), semver);
    assert.match(readInstallerVersion(), semver);
    assert.match(readBundledHmArchVersion(), semver);
  });
});
