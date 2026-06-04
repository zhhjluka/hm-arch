import type { ParsedCliArgs } from "./parse-args.js";
import {
  detectPlatform,
  environmentDiagnostics,
  formatDiagnostics,
  hasBlockingDiagnostics,
  platformSummary,
} from "./platform.js";

const NOT_IMPLEMENTED =
  "This command is scaffolded only (MEM-49). Python delegation arrives in MEM-51.";

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
    case "uninstall":
    case "upgrade":
      return runStub(parsed.command, parsed);
    default:
      return 2;
  }
}

function runDoctor(parsed: ParsedCliArgs): number {
  const info = detectPlatform();
  console.log(platformSummary(info));
  console.log("");
  console.log(formatDiagnostics(environmentDiagnostics(info)));
  if (parsed.agent) {
    console.log(`\nAgent scope: ${parsed.agent}${parsed.global ? " (global)" : ""}`);
  }
  return hasBlockingDiagnostics(environmentDiagnostics(info)) ? 1 : 0;
}

function runStatus(parsed: ParsedCliArgs): number {
  console.log(platformSummary());
  if (parsed.agent) {
    console.log(`agent: ${parsed.agent}${parsed.global ? " (global)" : ""}`);
  } else {
    console.log("agent: all supported agents");
  }
  console.log(`installer: ${NOT_IMPLEMENTED}`);
  return 0;
}

function runStub(command: "install" | "uninstall" | "upgrade", parsed: ParsedCliArgs): number {
  const agent = parsed.agent;
  console.error(`${command}${agent ? ` ${agent}` : ""}: ${NOT_IMPLEMENTED}`);
  return 2;
}
