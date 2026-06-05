import type { ParsedCliArgs } from "./parse-args.js";
import { delegateParsedCommand } from "./hm-arch-cli.js";
import { ensureManagedPythonEnv, formatEnsureResult } from "./python-env.js";
import {
  environmentDiagnostics,
  formatDiagnostics,
  hasBlockingDiagnostics,
} from "./platform.js";

export function runParsedCommand(parsed: ParsedCliArgs): number {
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

function runUpgrade(parsed: ParsedCliArgs): number {
  const code = ensurePythonRuntime({ upgrade: true });
  if (code !== 0) {
    return code;
  }
  if (!parsed.agent) {
    return 0;
  }
  return delegateParsedCommand(parsed);
}

function runWithManagedCli(
  parsed: ParsedCliArgs,
  options: { upgrade: boolean },
): number {
  const needsFreshEnv =
    parsed.command === "install" || parsed.command === "upgrade";
  const code = ensurePythonRuntime({
    upgrade: options.upgrade,
    quiet: !needsFreshEnv,
  });
  if (code !== 0) {
    return code;
  }
  return delegateParsedCommand(parsed);
}

function ensurePythonRuntime(options: {
  upgrade: boolean;
  quiet?: boolean;
}): number {
  try {
    const result = ensureManagedPythonEnv({ upgrade: options.upgrade });
    if (!options.quiet) {
      console.log(formatEnsureResult(result));
    }
    return 0;
  } catch (error) {
    if (error instanceof Error && error.message === "python_missing") {
      console.error(formatDiagnostics(environmentDiagnostics()));
      return 1;
    }
    const message = error instanceof Error ? error.message : String(error);
    console.error(`Failed to prepare managed Python environment: ${message}`);
    return 1;
  }
}
