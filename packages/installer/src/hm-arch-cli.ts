import { spawnSync } from "node:child_process";
import type { SpawnSyncReturns } from "node:child_process";
import { existsSync } from "node:fs";

import type { ParsedCliArgs } from "./parse-args.js";
import type { CliCommand } from "./constants.js";
import { managedHmArchExecutable, resolveHmArchHome } from "./paths.js";

export type HmArchCliDeps = {
  hmArchHome?: string;
  exists?: (path: string) => boolean;
  spawn?: (
    file: string,
    args: string[],
    options: { encoding: "utf8" },
  ) => SpawnSyncReturns<string>;
  stdout?: NodeJS.WriteStream;
  stderr?: NodeJS.WriteStream;
};

const DELEGATED_COMMANDS = new Set<CliCommand>([
  "install",
  "status",
  "doctor",
  "uninstall",
]);

function defaultSpawn(
  file: string,
  args: string[],
  options: { encoding: "utf8" },
): SpawnSyncReturns<string> {
  return spawnSync(file, args, { ...options, stdio: ["ignore", "pipe", "pipe"] });
}

export function resolveManagedHmArchExecutable(
  deps: HmArchCliDeps = {},
): { executable: string } | { error: string; exitCode: number } {
  const home = deps.hmArchHome ?? resolveHmArchHome();
  const executable = managedHmArchExecutable(home);
  const exists = deps.exists ?? existsSync;
  if (!exists(executable)) {
    return {
      error: [
        `Managed hm-arch CLI not found at ${executable}.`,
        "Run `hm-arch-install upgrade` to create or refresh the managed Python environment,",
        "or set HM_ARCH_HOME if you use a custom layout.",
      ].join("\n"),
      exitCode: 1,
    };
  }
  return { executable };
}

/** Map npm installer argv to ``hm-arch`` management subcommand argv. */
export function buildHmArchArgv(parsed: ParsedCliArgs): string[] {
  const command = parsed.command;
  if (!command) {
    return [];
  }

  if (command === "upgrade") {
    if (!parsed.agent) {
      return [];
    }
    return buildHmArchArgv({
      ...parsed,
      command: "install",
    });
  }

  if (!DELEGATED_COMMANDS.has(command)) {
    return [];
  }

  const args: string[] = [command];
  if (parsed.agent) {
    args.push(parsed.agent);
  }
  if (parsed.global) {
    args.push("--global");
  }
  return args;
}

function writeStream(stream: NodeJS.WriteStream, text: string): void {
  if (text.length > 0) {
    stream.write(text);
  }
}

export function forwardHmArchOutput(
  result: Pick<SpawnSyncReturns<string>, "stdout" | "stderr">,
  deps: Pick<HmArchCliDeps, "stdout" | "stderr"> = {},
): void {
  const stdout = deps.stdout ?? process.stdout;
  const stderr = deps.stderr ?? process.stderr;
  writeStream(stdout, result.stdout ?? "");
  writeStream(stderr, result.stderr ?? "");
}

export function runManagedHmArch(
  argv: string[],
  deps: HmArchCliDeps = {},
): { exitCode: number; spawnError?: string } {
  const resolved = resolveManagedHmArchExecutable(deps);
  if ("error" in resolved) {
    return { exitCode: resolved.exitCode, spawnError: resolved.error };
  }

  const spawn = deps.spawn ?? defaultSpawn;
  const result = spawn(resolved.executable, argv, { encoding: "utf8" });

  if (result.error) {
    return {
      exitCode: 1,
      spawnError: `Failed to run managed hm-arch: ${result.error.message}`,
    };
  }

  forwardHmArchOutput(result, deps);
  return { exitCode: result.status ?? 1 };
}

export function delegateParsedCommand(
  parsed: ParsedCliArgs,
  deps: HmArchCliDeps = {},
): number {
  const argv = buildHmArchArgv(parsed);
  if (argv.length === 0) {
    return 0;
  }

  const { exitCode, spawnError } = runManagedHmArch(argv, deps);
  if (spawnError) {
    console.error(spawnError);
  }
  return exitCode;
}
