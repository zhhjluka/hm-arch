import type { EnsureManagedEnvResult } from "./python-env.js";
import { ensureManagedPythonEnv, formatEnsureResult } from "./python-env.js";
import type { EnsureStandaloneBinaryResult } from "./standalone-binary.js";
import {
  ensureStandaloneBinary,
  formatEnsureStandaloneResult,
  prefersStandaloneRuntime,
  requiresStandaloneRuntime,
  standaloneTargetAvailable,
} from "./standalone-binary.js";
import { unsupportedReleaseTargetDiagnostic } from "./release-target.js";

export type RuntimeKind = "standalone" | "python";

export type EnsureRuntimeResult = {
  kind: RuntimeKind;
  standalone?: EnsureStandaloneBinaryResult;
  python?: EnsureManagedEnvResult;
};

export async function ensureHmArchRuntime(
  options: { upgrade?: boolean } = {},
): Promise<EnsureRuntimeResult> {
  const useStandalone = prefersStandaloneRuntime();

  if (useStandalone) {
    try {
      const standalone = await ensureStandaloneBinary({ upgrade: options.upgrade });
      return { kind: "standalone", standalone };
    } catch (error) {
      if (requiresStandaloneRuntime()) {
        throw error;
      }
      if (!standaloneTargetAvailable()) {
        throw error;
      }
      // Fall through to Python when auto mode and standalone provisioning fails.
    }
  }

  if (!standaloneTargetAvailable() && requiresStandaloneRuntime()) {
    const diagnostic = unsupportedReleaseTargetDiagnostic();
    throw new Error(diagnostic.message);
  }

  const python = ensureManagedPythonEnv({ upgrade: options.upgrade });
  return { kind: "python", python };
}

export function formatEnsureRuntimeResult(result: EnsureRuntimeResult): string {
  if (result.kind === "standalone" && result.standalone) {
    return formatEnsureStandaloneResult(result.standalone);
  }
  if (result.kind === "python" && result.python) {
    return formatEnsureResult(result.python);
  }
  return "HM-Arch runtime ready.";
}
