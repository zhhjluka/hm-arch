#!/usr/bin/env node
/**
 * Writes src/bundled-version.json from the monorepo hm_arch version file.
 * Run before TypeScript compile so the published package does not read repo paths.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const installerRoot = join(scriptDir, "..");
const versionFile = join(installerRoot, "..", "..", "src", "hm_arch", "_version.py");
const outFile = join(installerRoot, "src", "bundled-version.json");

const text = readFileSync(versionFile, "utf8");
const match = /__version__\s*=\s*["']([^"']+)["']/.exec(text);
if (!match) {
  console.error(`Could not parse __version__ from ${versionFile}`);
  process.exit(1);
}

writeFileSync(outFile, `${JSON.stringify({ version: match[1] }, null, 2)}\n`, "utf8");
console.error(`Wrote bundled hm-arch version ${match[1]} to ${outFile}`);
