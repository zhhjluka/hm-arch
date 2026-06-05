import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  artifactSuffix,
  detectReleaseTarget,
  normalizeNodeArch,
  normalizeNodeOs,
  releaseArtifactFilename,
  unsupportedReleaseTargetDiagnostic,
} from "../src/release-target.js";

describe("release target", () => {
  it("maps supported node platforms to release targets", () => {
    assert.deepEqual(detectReleaseTarget({ platform: "linux", arch: "x64" }), {
      os: "linux",
      arch: "x86_64",
    });
    assert.deepEqual(detectReleaseTarget({ platform: "linux", arch: "arm64" }), {
      os: "linux",
      arch: "aarch64",
    });
    assert.deepEqual(detectReleaseTarget({ platform: "darwin", arch: "arm64" }), {
      os: "darwin",
      arch: "arm64",
    });
    assert.deepEqual(detectReleaseTarget({ platform: "win32", arch: "x64" }), {
      os: "windows",
      arch: "x86_64",
    });
  });

  it("rejects unsupported darwin x64 and windows arm64", () => {
    assert.equal(detectReleaseTarget({ platform: "darwin", arch: "x64" }), null);
    assert.equal(detectReleaseTarget({ platform: "win32", arch: "arm64" }), null);
  });

  it("builds versioned artifact filenames", () => {
    const linux = { os: "linux" as const, arch: "x86_64" as const };
    assert.equal(
      releaseArtifactFilename("1.2.3", linux),
      "hm-arch-1.2.3-linux-x86_64",
    );
    const windows = { os: "windows" as const, arch: "x86_64" as const };
    assert.equal(
      releaseArtifactFilename("1.2.3", windows),
      "hm-arch-1.2.3-windows-x86_64.exe",
    );
    assert.equal(artifactSuffix(linux), "linux-x86_64");
  });

  it("normalizeNodeArch respects darwin arm64 naming", () => {
    assert.equal(normalizeNodeOs("darwin"), "darwin");
    assert.equal(normalizeNodeArch("arm64", "darwin"), "arm64");
    assert.equal(normalizeNodeArch("arm64", "linux"), "aarch64");
  });

  it("unsupportedReleaseTargetDiagnostic includes actionable hints", () => {
    const intel = unsupportedReleaseTargetDiagnostic("darwin", "x64");
    assert.equal(intel.code, "unsupported_release_target");
    assert.match(intel.hint ?? "", /Intel Mac/i);

    const winArm = unsupportedReleaseTargetDiagnostic("win32", "arm64");
    assert.match(winArm.hint ?? "", /Windows ARM64/i);
  });
});
