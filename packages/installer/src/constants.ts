/** Supported agent identifiers (mirrors Python ``ALL_AGENTS``). */
export const SUPPORTED_AGENTS = ["codex", "claude-code", "hermes"] as const;

export type SupportedAgent = (typeof SUPPORTED_AGENTS)[number];

export const CLI_COMMANDS = [
  "install",
  "status",
  "doctor",
  "upgrade",
  "uninstall",
] as const;

export type CliCommand = (typeof CLI_COMMANDS)[number];

/** Minimum Node.js major version for the installer. */
export const MIN_NODE_MAJOR = 18;

/** Minimum Python version (major.minor) required by the HM-Arch Python package. */
export const MIN_PYTHON = "3.10";

/** OS families the installer is designed to support (v1.2.0). */
export const SUPPORTED_OS = new Set(["darwin", "linux", "win32"]);
