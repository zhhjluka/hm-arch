#!/usr/bin/env node

import { realpathSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";

import { runParsedCommand } from "./commands.js";
import { parseCliArgs, usageText } from "./parse-args.js";

export async function main(argv: string[] = process.argv.slice(2)): Promise<number> {
  const parsed = parseCliArgs(argv);
  if (parsed.help || (!parsed.command && !parsed.error)) {
    console.log(usageText());
    return parsed.error ? 2 : 0;
  }
  return runParsedCommand(parsed);
}

function isCliEntry(): boolean {
  if (import.meta.main === true) {
    return true;
  }
  const entry = process.argv[1];
  if (!entry) {
    return false;
  }
  try {
    const resolvedEntry = realpathSync(entry);
    const resolvedModule = realpathSync(fileURLToPath(import.meta.url));
    if (resolvedEntry === resolvedModule) {
      return true;
    }
    return import.meta.url === pathToFileURL(entry).href;
  } catch {
    return /(?:^|[\\/])(?:hm-arch-install|cli\.js)$/.test(entry);
  }
}

if (isCliEntry()) {
  main()
    .then((code) => process.exit(code))
    .catch((error: unknown) => {
      const message = error instanceof Error ? error.message : String(error);
      console.error(message);
      process.exit(1);
    });
}
