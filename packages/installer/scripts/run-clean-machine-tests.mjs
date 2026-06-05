#!/usr/bin/env node
/**
 * Run MEM-64 clean-machine tests with a minimal environment (no Python on PATH).
 * Requires HM_ARCH_STANDALONE_FIXTURE pointing at a built hm-arch standalone binary.
 */
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const installerRoot = join(scriptDir, "..");
const fixture = process.env.HM_ARCH_STANDALONE_FIXTURE;

if (!fixture || !existsSync(fixture)) {
  console.error(
    "HM_ARCH_STANDALONE_FIXTURE must point at a built standalone hm-arch executable.",
  );
  process.exit(1);
}

const nodeBin = dirname(process.execPath);
const minimalPath = nodeBin;

const env = {
  ...process.env,
  PATH: minimalPath,
  HM_ARCH_STANDALONE_FIXTURE: fixture,
};
delete env.HM_ARCH_PYTHON;
delete env.VIRTUAL_ENV;

for (const name of ["python3", "python", "python3.12", "python3.11", "python3.10"]) {
  const probe = spawnSync("sh", ["-c", `command -v ${name} >/dev/null 2>&1`], { env });
  if (probe.status === 0) {
    console.error(`Refusing to run clean-machine tests: ${name} is still on PATH`);
    process.exit(1);
  }
}

const testFiles = [
  join(installerRoot, "test", "clean-machine-standalone.test.ts"),
  join(installerRoot, "test", "version-coordination.test.ts"),
];

const result = spawnSync(
  process.execPath,
  ["--import", "tsx", "--test", ...testFiles],
  { stdio: "inherit", cwd: installerRoot, env },
);

process.exit(result.status ?? 1);
