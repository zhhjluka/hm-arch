import type { ParsedCliArgs } from "./parse-args.js";
import {
  describeManagedEnv,
  ensureManagedPythonEnv,
  formatEnsureResult,
  formatManagedEnvSummary,
} from "./python-env.js";
import {
  detectPlatform,
  environmentDiagnostics,
  formatDiagnostics,
  hasBlockingDiagnostics,
  platformSummary,
} from "./platform.js";

const AGENT_NOT_IMPLEMENTED =
  "Agent hook configuration is not implemented yet (MEM-51). The managed Python runtime is ready.";

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
      return runDoctor(parsed);
    case "status":
      return runStatus(parsed);
    case "install":
      return runInstall(parsed);
    case "upgrade":
      return runUpgrade(parsed);
    case "uninstall":
      return runUninstallStub(parsed);
    default:
      return 2;
  }
}

function runDoctor(parsed: ParsedCliArgs): number {
  const info = detectPlatform();
  console.log(platformSummary(info));
  console.log("");
  console.log(formatDiagnostics(environmentDiagnostics(info)));
  console.log("");
  console.log(formatManagedEnvSummary(describeManagedEnv()));
  if (parsed.agent) {
    console.log(`\nAgent scope: ${parsed.agent}${parsed.global ? " (global)" : ""}`);
  }
  const blocking = hasBlockingDiagnostics(environmentDiagnostics(info));
  const managed = describeManagedEnv();
  if (!blocking && !managed.hmArchImportable) {
    console.log(
      "\nNote: hm-arch is not installed in the managed venv yet. Run `hm-arch-install install <agent>` or `hm-arch-install upgrade`.",
    );
  }
  return blocking ? 1 : 0;
}

function runStatus(parsed: ParsedCliArgs): number {
  console.log(platformSummary());
  console.log("");
  console.log(formatManagedEnvSummary(describeManagedEnv()));
  if (parsed.agent) {
    console.log(`\nagent: ${parsed.agent}${parsed.global ? " (global)" : ""}`);
  } else {
    console.log("\nagent: all supported agents (configuration pending MEM-51)");
  }
  return 0;
}

function runInstall(parsed: ParsedCliArgs): number {
  const code = ensurePythonRuntime({ upgrade: false });
  if (code !== 0) {
    return code;
  }
  const agent = parsed.agent;
  console.log(`\ninstall ${agent}${parsed.global ? " --global" : ""}: ${AGENT_NOT_IMPLEMENTED}`);
  return 0;
}

function runUpgrade(parsed: ParsedCliArgs): number {
  const code = ensurePythonRuntime({ upgrade: true });
  if (code !== 0) {
    return code;
  }
  if (parsed.agent) {
    console.log(`\nupgrade ${parsed.agent}${parsed.global ? " --global" : ""}: ${AGENT_NOT_IMPLEMENTED}`);
  }
  return 0;
}

function runUninstallStub(parsed: ParsedCliArgs): number {
  const agent = parsed.agent;
  console.error(
    `uninstall ${agent}${parsed.global ? " --global" : ""}: Agent uninstall is not implemented yet (MEM-51).`,
  );
  return 2;
}

function ensurePythonRuntime(options: { upgrade: boolean }): number {
  try {
    const result = ensureManagedPythonEnv({ upgrade: options.upgrade });
    console.log(formatEnsureResult(result));
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
