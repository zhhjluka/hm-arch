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

/** Environment variable overriding the managed-runtime home directory. */
export const ENV_HM_ARCH_HOME = "HM_ARCH_HOME";

/** Environment variable overriding the pip requirement for hm-arch. */
export const ENV_HM_ARCH_PIP_SPEC = "HM_ARCH_PIP_SPEC";

/**
 * Runtime selection: ``auto`` (standalone when supported, else Python),
 * ``standalone``, or ``python``.
 */
export const ENV_HM_ARCH_RUNTIME = "HM_ARCH_RUNTIME";

/** Override GitHub release download base URL (for tests or mirrors). */
export const ENV_HM_ARCH_RELEASE_BASE_URL = "HM_ARCH_RELEASE_BASE_URL";

/** Default GitHub repository for standalone release assets. */
export const DEFAULT_GITHUB_REPO = "ZhangHangjianMA/hm-arch";

/** OS families the installer is designed to support (v1.2.0). */
export const SUPPORTED_OS = new Set(["darwin", "linux", "win32"]);
