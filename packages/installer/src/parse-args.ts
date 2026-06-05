import {
  CLI_COMMANDS,
  SUPPORTED_AGENTS,
  type CliCommand,
  type SupportedAgent,
} from "./constants.js";

export type ParsedCliArgs = {
  command?: CliCommand;
  agent?: SupportedAgent;
  global: boolean;
  help: boolean;
  error?: string;
};

function isSupportedAgent(value: string): value is SupportedAgent {
  return (SUPPORTED_AGENTS as readonly string[]).includes(value);
}

function isCliCommand(value: string): value is CliCommand {
  return (CLI_COMMANDS as readonly string[]).includes(value);
}

const SUPPORTED_FLAGS = new Set(["--global", "-g", "--help", "-h"]);

function findUnknownFlag(argv: string[]): string | undefined {
  return argv.find((arg) => arg.startsWith("-") && !SUPPORTED_FLAGS.has(arg));
}

/**
 * Parse ``hm-arch-install`` argv (without node executable prefix).
 * Mirrors the Python ``hm-arch`` management subcommands at a high level.
 */
export function parseCliArgs(argv: string[]): ParsedCliArgs {
  const unknownFlag = findUnknownFlag(argv);
  if (unknownFlag !== undefined) {
    return {
      global: false,
      help: false,
      error: `Unknown option ${JSON.stringify(unknownFlag)}. Supported options: --global (-g), --help (-h).`,
    };
  }

  const global = argv.includes("--global") || argv.includes("-g");
  const help = argv.includes("--help") || argv.includes("-h");
  const positional = argv.filter((arg) => !arg.startsWith("-"));

  if (positional.length === 0) {
    return { global, help };
  }

  const [command, maybeAgent, extra] = positional;
  if (!isCliCommand(command)) {
    return {
      global,
      help,
      error: `Unknown command ${JSON.stringify(command)}. Expected one of: ${CLI_COMMANDS.join(", ")}.`,
    };
  }

  if (extra !== undefined) {
    return {
      global,
      help,
      error: `Unexpected argument ${JSON.stringify(extra)}.`,
    };
  }

  if (command === "install" || command === "uninstall") {
    if (!maybeAgent) {
      return {
        global,
        help,
        error: `${command} requires an agent (${SUPPORTED_AGENTS.join(", ")}).`,
      };
    }
    if (!isSupportedAgent(maybeAgent)) {
      return {
        global,
        help,
        error: `Unsupported agent ${JSON.stringify(maybeAgent)}. Choose from: ${SUPPORTED_AGENTS.join(", ")}.`,
      };
    }
    return { command, agent: maybeAgent, global, help };
  }

  if (maybeAgent !== undefined) {
    if (!isSupportedAgent(maybeAgent)) {
      return {
        global,
        help,
        error: `Unsupported agent ${JSON.stringify(maybeAgent)}. Choose from: ${SUPPORTED_AGENTS.join(", ")}.`,
      };
    }
    return { command, agent: maybeAgent, global, help };
  }

  return { command, global, help };
}

export function usageText(): string {
  return `hm-arch-install — HM-Arch npm installer

Usage:
  hm-arch-install install <agent> [--global]
  hm-arch-install uninstall <agent> [--global]
  hm-arch-install status [agent] [--global]
  hm-arch-install doctor [agent] [--global]
  hm-arch-install upgrade [agent] [--global]

Agents: ${SUPPORTED_AGENTS.join(", ")}

Environment variables:
  HM_ARCH_HOME       Directory for the managed venv (default: ~/.hm-arch)
  HM_ARCH_PYTHON     Path to a Python 3.10+ interpreter used to create the venv
  HM_ARCH_PIP_SPEC   pip requirement for hm-arch (default: hm-arch==<bundled>)

Agent install/status/doctor/uninstall commands delegate to the managed \`hm-arch\` CLI.
\`upgrade\` refreshes the managed Python package; with an agent, re-runs \`hm-arch install\`.
npm postinstall is a no-op; run install explicitly.
`;
}
