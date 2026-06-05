import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";

const INSTALLER_ROOT = join(import.meta.dirname, "..");

describe("packed installer tarball", () => {
  it("hm-arch-install --help works after npm pack and install", () => {
    const packJson = execFileSync("npm", ["pack", "--json", "--silent"], {
      cwd: INSTALLER_ROOT,
      encoding: "utf8",
    });
    const tarballName = (JSON.parse(packJson) as Array<{ filename: string }>)[0]?.filename;
    assert.ok(tarballName, "npm pack should return a tarball filename");
    const tarballPath = join(INSTALLER_ROOT, tarballName);
    const projectDir = mkdtempSync(join(tmpdir(), "hm-arch-pack-smoke-"));
    try {
      execFileSync("npm", ["init", "-y"], { cwd: projectDir, stdio: "ignore" });
      execFileSync("npm", ["install", tarballPath], { cwd: projectDir, stdio: "ignore" });
      const help = execFileSync(
        join(projectDir, "node_modules", ".bin", "hm-arch-install"),
        ["--help"],
        { encoding: "utf8" },
      );
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
