import type { ParsedCliArgs } from "./parse-args.js";
import { delegateParsedCommand } from "./hm-arch-cli.js";
import {
  environmentDiagnostics,
  formatDiagnostics,
  hasBlockingDiagnostics,
} from "./platform.js";
import {
  ensureHmArchRuntime as provisionHmArchRuntime,
  formatEnsureRuntimeResult,
} from "./runtime.js";

export async function runParsedCommand(parsed: ParsedCliArgs): Promise<number> {
  if (parsed.help) {
    return 0;
  }
  if (parsed.error) {
    console.error(parsed.error);
    return 2;
  }
  if (!parsed.command) {
    return 2;
  }

  const diagnostics = environmentDiagnostics();
  if (hasBlockingDiagnostics(diagnostics) && parsed.command !== "doctor") {
    console.error(formatDiagnostics(diagnostics));
    console.error(
      "\nRun `hm-arch-install doctor` for environment details, or fix the issues above.",
    );
    return 1;
  }

  switch (parsed.command) {
    case "doctor":
      return runWithManagedCli(parsed, { upgrade: false });
    case "status":
      return runWithManagedCli(parsed, { upgrade: false });
    case "install":
      return runWithManagedCli(parsed, { upgrade: false });
    case "upgrade":
      return runUpgrade(parsed);
    case "uninstall":
      return runWithManagedCli(parsed, { upgrade: false });
    default:
      return 2;
  }
}

async function runUpgrade(parsed: ParsedCliArgs): Promise<number> {
  const code = await prepareHmArchRuntime({ upgrade: true });
  if (code !== 0) {
    return code;
  }
  if (!parsed.agent) {
    return 0;
  }
  return delegateParsedCommand(parsed);
}

async function runWithManagedCli(
  parsed: ParsedCliArgs,
  options: { upgrade: boolean },
): Promise<number> {
  const needsFreshEnv =
    parsed.command === "install" || parsed.command === "upgrade";
  const code = await prepareHmArchRuntime({
    upgrade: options.upgrade,
    quiet: !needsFreshEnv,
  });
  if (code !== 0) {
    return code;
  }
  return delegateParsedCommand(parsed);
}

async function prepareHmArchRuntime(options: {
  upgrade: boolean;
  quiet?: boolean;
}): Promise<number> {
  try {
    const result = await provisionHmArchRuntime({ upgrade: options.upgrade });
    if (!options.quiet) {
      console.log(formatEnsureRuntimeResult(result));
    }
    return 0;
  } catch (error) {
    if (error instanceof Error) {
      if (error.message === "python_missing") {
        console.error(formatDiagnostics(environmentDiagnostics()));
        return 1;
      }
      if (error.message.includes("No standalone HM-Arch binary")) {
        console.error(formatDiagnostics(environmentDiagnostics()));
        return 1;
      }
    }
    const message = error instanceof Error ? error.message : String(error);
    console.error(`Failed to prepare HM-Arch runtime: ${message}`);
    return 1;
  }
}
