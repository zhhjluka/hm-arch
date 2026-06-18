import { readdirSync } from "node:fs";
import { spawn } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const packageDir = dirname(fileURLToPath(import.meta.url));
const distTestDir = join(packageDir, "../dist-test");

function listTests() {
  return readdirSync(distTestDir)
    .filter((name) => name.endsWith(".test.js"))
    .map((name) => join(distTestDir, name));
}

const tests = listTests();
if (tests.length === 0) {
  console.error("No compiled tests found in dist-test/");
  process.exit(1);
}

const child = spawn(process.execPath, ["--test", ...tests], {
  stdio: "inherit",
  cwd: packageDir,
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.exit(1);
  }
  process.exit(code ?? 1);
});
