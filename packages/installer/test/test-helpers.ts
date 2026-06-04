import { probeSupportedPython } from "../src/platform.js";

/** True when a Python >= MIN_PYTHON interpreter is available for integration tests. */
export function hasSupportedPython(): boolean {
  return probeSupportedPython() !== null;
}

/** Apply HM_ARCH_PYTHON for tests when a supported interpreter is available. */
export function withSupportedPythonEnv<T>(fn: () => T): T {
  const python = probeSupportedPython();
  if (!python) {
    throw new Error("supported Python interpreter required");
  }
  const previous = process.env.HM_ARCH_PYTHON;
  process.env.HM_ARCH_PYTHON = python.executable;
  try {
    return fn();
  } finally {
    if (previous === undefined) {
      delete process.env.HM_ARCH_PYTHON;
    } else {
      process.env.HM_ARCH_PYTHON = previous;
    }
  }
}
