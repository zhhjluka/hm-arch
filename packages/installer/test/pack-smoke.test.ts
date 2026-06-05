import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";

import { execNpmSync, localPackageBin } from "./test-helpers.js";

const INSTALLER_ROOT = join(import.meta.dirname, "..");

describe("packed installer tarball", () => {
  it("hm-arch-install --help works after npm pack and install", () => {
    const packJson = execNpmSync(["pack", "--json", "--silent"], {
      cwd: INSTALLER_ROOT,
      encoding: "utf8",
    });
    const tarballName = (JSON.parse(packJson) as Array<{ filename: string }>)[0]?.filename;
    assert.ok(tarballName, "npm pack should return a tarball filename");
    const tarballPath = join(INSTALLER_ROOT, tarballName);
    const projectDir = mkdtempSync(join(tmpdir(), "hm-arch-pack-smoke-"));
    try {
      execNpmSync(["init", "-y"], { cwd: projectDir, stdio: "ignore" });
      execNpmSync(["install", tarballPath], { cwd: projectDir, stdio: "ignore" });
      const help = execFileSync(localPackageBin(projectDir, "hm-arch-install"), ["--help"], {
        encoding: "utf8",
        shell: process.platform === "win32",
      });
      assert.match(help, /hm-arch-install/);
      const bundled = JSON.parse(
        readFileSync(
          join(projectDir, "node_modules", "@hm-arch", "installer", "dist", "bundled-version.json"),
          "utf8",
        ),
      ) as { version: string };
      assert.match(bundled.version, /^\d+\.\d+\.\d+$/);
    } finally {
      rmSync(projectDir, { recursive: true, force: true });
      rmSync(tarballPath, { force: true });
    }
  });
});
