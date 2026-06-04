import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const INSTALLER_PACKAGE_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

/**
 * PyPI package version the installer installs into its managed venv.
 * Parsed from the monorepo ``src/hm_arch/_version.py`` at module load time.
 */
export function readBundledHmArchVersion(
  overrides?: { versionFilePath?: string },
): string {
  const versionFile =
    overrides?.versionFilePath ??
    join(INSTALLER_PACKAGE_ROOT, "..", "..", "src", "hm_arch", "_version.py");
  const text = readFileSync(versionFile, "utf8");
  const match = /__version__\s*=\s*["']([^"']+)["']/.exec(text);
  if (!match) {
    throw new Error(`Could not parse __version__ from ${versionFile}`);
  }
  return match[1];
}

/** Default hm-arch version bundled with this installer release. */
export const BUNDLED_HM_ARCH_VERSION = readBundledHmArchVersion();
