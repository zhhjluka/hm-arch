#!/usr/bin/env node
/**
 * Writes src/bundled-version.json and src/installer-version.json for the npm package.
 * Run before TypeScript compile so the published package does not read repo paths.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const installerRoot = join(scriptDir, "..");
const versionFile = join(installerRoot, "..", "..", "src", "hm_arch", "_version.py");
const packageJsonFile = join(installerRoot, "package.json");
const bundledOutFile = join(installerRoot, "src", "bundled-version.json");
const installerOutFile = join(installerRoot, "src", "installer-version.json");

const text = readFileSync(versionFile, "utf8");
const match = /__version__\s*=\s*["']([^"']+)["']/.exec(text);
if (!match) {
  console.error(`Could not parse __version__ from ${versionFile}`);
  process.exit(1);
}

const packageJson = JSON.parse(readFileSync(packageJsonFile, "utf8"));
if (!packageJson.version || typeof packageJson.version !== "string") {
  console.error(`Could not read version from ${packageJsonFile}`);
  process.exit(1);
}

writeFileSync(bundledOutFile, `${JSON.stringify({ version: match[1] }, null, 2)}\n`, "utf8");
console.error(`Wrote bundled hm-arch version ${match[1]} to ${bundledOutFile}`);

writeFileSync(
  installerOutFile,
  `${JSON.stringify({ version: packageJson.version }, null, 2)}\n`,
  "utf8",
);
console.error(`Wrote installer version ${packageJson.version} to ${installerOutFile}`);
