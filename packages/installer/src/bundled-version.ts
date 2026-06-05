import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const BUNDLED_VERSION_FILE = join(dirname(fileURLToPath(import.meta.url)), "bundled-version.json");

export type BundledVersionPayload = {
  version: string;
};

/**
 * Paired hm-arch PyPI version shipped with this installer release.
 * Loaded from ``bundled-version.json`` next to the compiled module (generated at build).
 */
export function readBundledHmArchVersion(
  overrides?: { bundledVersionPath?: string },
): string {
  const path = overrides?.bundledVersionPath ?? BUNDLED_VERSION_FILE;
  const payload = JSON.parse(readFileSync(path, "utf8")) as BundledVersionPayload;
  if (!payload.version || typeof payload.version !== "string") {
    throw new Error(`Invalid bundled version file: ${path}`);
  }
  return payload.version;
}

/** Default hm-arch version bundled with this installer release. */
export const BUNDLED_HM_ARCH_VERSION = readBundledHmArchVersion();
