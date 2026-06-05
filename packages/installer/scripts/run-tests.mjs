#!/usr/bin/env node
/**
 * Cross-platform test runner for @hm-arch/installer.
 * Enumerates test/*.test.ts files and invokes node --test with explicit paths
 * (shell glob expansion is not portable on Windows or with node --test).
 */
import { spawnSync } from "node:child_process";
import { readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const installerRoot = join(scriptDir, "..");
const testDir = join(installerRoot, "test");

function collectTestFiles(dir) {
  const files = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectTestFiles(full));
    } else if (entry.isFile() && entry.name.endsWith(".test.ts")) {
      files.push(full);
    }
  }
  return files;
}

const testFiles = collectTestFiles(testDir).sort();
if (testFiles.length === 0) {
  console.error(`No test files found under ${testDir}`);
  process.exit(1);
}

const result = spawnSync(
  process.execPath,
  ["--import", "tsx", "--test", ...testFiles],
  { stdio: "inherit", cwd: installerRoot }
);

process.exit(result.status ?? 1);
