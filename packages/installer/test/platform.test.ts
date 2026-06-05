import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  detectPlatform,
  environmentDiagnostics,
  formatDiagnostics,
  hasBlockingDiagnostics,
  probePython,
  probeSupportedPython,
} from "../src/platform.js";

describe("platform detection", () => {
  it("detects injected platform fields", () => {
    const info = detectPlatform({
      platform: "linux",
      arch: "x64",
      nodeVersion: "v22.0.0",
      python: {
        executable: "python3",
        version: "3.12.1",
        major: 3,
        minor: 12,
      },
    });
    assert.equal(info.os, "linux");
    assert.equal(info.arch, "x64");
    assert.equal(info.nodeMajor, 22);
    assert.equal(info.python?.version, "3.12.1");
  });

  it("parses python version from probe output", () => {
    const python = probePython({
      executables: ["python3"],
      run: () => "Python 3.11.8\n",
    });
    assert.ok(python);
    assert.equal(python.version, "3.11.8");
    assert.equal(python.major, 3);
    assert.equal(python.minor, 11);
  });

  it("reports unsupported release target for darwin x64", () => {
    const diagnostics = environmentDiagnostics(
      detectPlatform({
        platform: "darwin",
        arch: "x64",
        nodeVersion: "v22.0.0",
        python: null,
      }),
    );
    assert.ok(diagnostics.some((item) => item.code === "unsupported_release_target"));
  });

  it("reports blocking errors for unsupported environments", () => {
    const diagnostics = environmentDiagnostics(
      detectPlatform({
        platform: "freebsd",
        arch: "x64",
        nodeVersion: "v16.0.0",
        python: null,
      }),
    );
    assert.ok(hasBlockingDiagnostics(diagnostics));
    const text = formatDiagnostics(diagnostics);
    assert.match(text, /unsupported_os/);
    assert.match(text, /unsupported_node/);
    assert.match(text, /python_missing/);
  });

  it("accepts supported linux + node 18 + python 3.10", () => {
    const diagnostics = environmentDiagnostics(
      detectPlatform({
        platform: "linux",
        arch: "arm64",
        nodeVersion: "v20.10.0",
        python: {
          executable: "python3",
          version: "3.10.0",
          major: 3,
          minor: 10,
        },
      }),
    );
    assert.equal(hasBlockingDiagnostics(diagnostics), false);
  });

  it("probeSupportedPython rejects interpreters below minimum", () => {
    const python = probeSupportedPython({
      executables: ["python3"],
      run: () => "Python 3.9.6\n",
    });
    assert.equal(python, null);
  });

  it("probeSupportedPython accepts interpreters at minimum", () => {
    const python = probeSupportedPython({
      executables: ["python3.10"],
      run: () => "Python 3.10.0\n",
    });
    assert.ok(python);
    assert.equal(python.version, "3.10.0");
  });

  it("flags python below minimum", () => {
    const diagnostics = environmentDiagnostics(
      detectPlatform({
        platform: "darwin",
        arch: "x64",
        nodeVersion: "v22.0.0",
        python: {
          executable: "python3",
          version: "3.9.18",
          major: 3,
          minor: 9,
        },
      }),
    );
    assert.ok(diagnostics.some((item) => item.code === "unsupported_python"));
  });
});
