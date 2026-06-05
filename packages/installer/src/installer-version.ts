import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const INSTALLER_VERSION_FILE = join(
  dirname(fileURLToPath(import.meta.url)),
  "installer-version.json",
);

export type InstallerVersionPayload = {
  version: string;
};

/**
 * npm package version for `@hm-arch/installer`.
 * Loaded from ``installer-version.json`` next to the compiled module (generated at build).
 */
export function readInstallerVersion(
  overrides?: { installerVersionPath?: string },
): string {
  const path = overrides?.installerVersionPath ?? INSTALLER_VERSION_FILE;
  const payload = JSON.parse(readFileSync(path, "utf8")) as InstallerVersionPayload;
  if (!payload.version || typeof payload.version !== "string") {
    throw new Error(`Invalid installer version file: ${path}`);
  }
  return payload.version;
}

/** Default npm installer package version for this release. */
export const INSTALLER_VERSION = readInstallerVersion();
