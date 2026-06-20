import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

describe("published package security", () => {
  it("has no production dependency audit findings", () => {
    const output = execFileSync("npm", ["audit", "--omit=dev", "--json"], {
      cwd: packageRoot,
      encoding: "utf8",
    });
    const report = JSON.parse(output) as {
      metadata?: { vulnerabilities?: { total?: number } };
    };
    assert.equal(report.metadata?.vulnerabilities?.total ?? 0, 0);
  });

  it("ships only dist and plugin manifest files", () => {
    const output = execFileSync("npm", ["pack", "--dry-run", "--json"], {
      cwd: packageRoot,
      encoding: "utf8",
    });
    const payload = JSON.parse(output) as Array<{
      files?: Array<{ path: string }>;
    }>;
    const files = payload[0]?.files?.map((entry) => entry.path) ?? [];
    assert.ok(files.length > 0);
    for (const filePath of files) {
      assert.match(
        filePath,
        /^(dist\/|openclaw\.plugin\.json$|package\.json$)/,
        `unexpected published file: ${filePath}`,
      );
    }
    assert.ok(!files.some((filePath) => filePath.includes("node_modules")));
  });
});
