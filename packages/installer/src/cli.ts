#!/usr/bin/env node

import { runParsedCommand } from "./commands.js";
import { parseCliArgs, usageText } from "./parse-args.js";

export function main(argv: string[] = process.argv.slice(2)): number {
  const parsed = parseCliArgs(argv);
  if (parsed.help || (!parsed.command && !parsed.error)) {
    console.log(usageText());
    return parsed.error ? 2 : 0;
  }
  return runParsedCommand(parsed);
}

if (import.meta.main) {
  process.exit(main());
}
