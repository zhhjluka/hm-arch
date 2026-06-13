import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";

import { sha256Buffer } from "../src/integrity.js";
import { parseReleaseMetadata } from "../src/release-metadata.js";
import {
  downloadVerifiedStandaloneArtifact,
  ensureStandaloneBinary,
  resolveReleaseBaseUrl,
  verifyDownloadedArtifact,
  verifyReleaseMetadataSignature,
} from "../src/standalone-binary.js";

const VERSION = "9.9.9";
const TARGET = { os: "linux" as const, arch: "x86_64" as const };
const FILENAME = `hm-arch-${VERSION}-linux-x86_64`;
const PAYLOAD = Buffer.from("standalone-binary-payload");

function sampleMetadata(digest: string) {
  return {
    schema_version: 1,
    package: "hm-arch",
    version: VERSION,
    artifacts: [
      {
        filename: FILENAME,
        os: "linux",
        arch: "x86_64",
        version: VERSION,
        sha256: digest,
        size_bytes: PAYLOAD.length,
      },
    ],
  };
}

function mockReleaseHandlers(
  options: {
    artifactBytes?: Buffer;
    metadata?: Record<string, unknown>;
    checksumSidecar?: string | null;
    corruptChecksum?: boolean;
  } = {},
) {
  const digest = sha256Buffer(options.artifactBytes ?? PAYLOAD);
  const metadata = options.metadata ?? sampleMetadata(digest);
  const checksumSidecar =
    options.checksumSidecar === null
      ? null
      : (options.checksumSidecar ??
        `${digest}  ${FILENAME}\n`);

  return {
    fetchText: async (url: string) => {
      if (url.endsWith("standalone-release-metadata.json")) {
        return JSON.stringify(metadata);
      }
      if (url.endsWith(".sha256")) {
        if (checksumSidecar === null) {
          throw new Error("checksum missing");
        }
        if (options.corruptChecksum) {
          return `deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef  ${FILENAME}\n`;
        }
        return checksumSidecar;
      }
      throw new Error(`unexpected text fetch: ${url}`);
    },
    fetchBuffer: async (url: string) => {
      if (url.endsWith(FILENAME)) {
        return options.artifactBytes ?? PAYLOAD;
      }
      throw new Error(`unexpected buffer fetch: ${url}`);
    },
  };
}

describe("standalone binary downloader", () => {
  it("uses the current GitHub repository for release downloads by default", () => {
    assert.equal(
      resolveReleaseBaseUrl(),
      "https://github.com/zhhjluka/hm-arch/releases/download",
    );
  });

  it("downloads and verifies artifact against metadata and checksum sidecar", async () => {
    const handlers = mockReleaseHandlers();
    const result = await downloadVerifiedStandaloneArtifact(
      { version: VERSION, target: TARGET },
      {
        releaseBaseUrl: "https://example.test/releases/download",
        ...handlers,
      },
    );
    assert.equal(result.record.filename, FILENAME);
    assert.equal(result.bytes.toString(), PAYLOAD.toString());
  });

  it("rejects corrupt artifact bytes", () => {
    const digest = sha256Buffer(PAYLOAD);
    const record = sampleMetadata(digest).artifacts[0];
    assert.throws(
      () => verifyDownloadedArtifact(Buffer.from("tampered"), record, null),
      /Checksum mismatch/,
    );
  });

  it("rejects metadata version mismatch", () => {
    const digest = sha256Buffer(PAYLOAD);
    const metadata = parseReleaseMetadata(JSON.stringify(sampleMetadata(digest)));
    assert.throws(
      () => verifyReleaseMetadataSignature(metadata, "1.0.0"),
      /version mismatch/,
    );
  });

  it("rejects corrupt checksum sidecar", async () => {
    await assert.rejects(
      downloadVerifiedStandaloneArtifact(
        { version: VERSION, target: TARGET },
        {
          releaseBaseUrl: "https://example.test/releases/download",
          ...mockReleaseHandlers({ corruptChecksum: true }),
        },
      ),
      /Checksum mismatch/,
    );
  });

  it("rejects metadata with mismatched artifact size", async () => {
    const digest = sha256Buffer(PAYLOAD);
    const badMetadata = sampleMetadata(digest);
    badMetadata.artifacts[0].size_bytes = PAYLOAD.length + 1;
    await assert.rejects(
      downloadVerifiedStandaloneArtifact(
        { version: VERSION, target: TARGET },
        {
          releaseBaseUrl: "https://example.test/releases/download",
          ...mockReleaseHandlers({ metadata: badMetadata }),
        },
      ),
      /Size mismatch/,
    );
  });

  it("installs verified binary into HM_ARCH_HOME", async () => {
    const home = mkdtempSync(join(tmpdir(), "hm-arch-standalone-"));
    const previousRuntime = process.env.HM_ARCH_RUNTIME;
    process.env.HM_ARCH_RUNTIME = "standalone";
    try {
      const result = await ensureStandaloneBinary(
        {},
        {
          hmArchHome: home,
          targetVersion: VERSION,
          target: TARGET,
          releaseBaseUrl: "https://example.test/releases/download",
          ...mockReleaseHandlers(),
        },
      );
      assert.equal(result.action, "created");
      const installed = readFileSync(result.executable);
      assert.equal(installed.toString(), PAYLOAD.toString());
      assert.equal(result.state.sha256, sha256Buffer(PAYLOAD));
    } finally {
      if (previousRuntime === undefined) {
        delete process.env.HM_ARCH_RUNTIME;
      } else {
        process.env.HM_ARCH_RUNTIME = previousRuntime;
      }
      rmSync(home, { recursive: true, force: true });
    }
  });

  it("reuses installed binary when version matches", async () => {
    const home = mkdtempSync(join(tmpdir(), "hm-arch-standalone-reuse-"));
    let fetchCount = 0;
    const handlers = mockReleaseHandlers();
    const countingHandlers = {
      ...handlers,
      fetchBuffer: async (url: string) => {
        fetchCount += 1;
        return handlers.fetchBuffer(url);
      },
    };
    try {
      await ensureStandaloneBinary(
        {},
        {
          hmArchHome: home,
          targetVersion: VERSION,
          target: TARGET,
          releaseBaseUrl: "https://example.test/releases/download",
          ...countingHandlers,
        },
      );
      fetchCount = 0;
      const reused = await ensureStandaloneBinary(
        {},
        {
          hmArchHome: home,
          targetVersion: VERSION,
          target: TARGET,
          releaseBaseUrl: "https://example.test/releases/download",
          ...countingHandlers,
        },
      );
      assert.equal(reused.action, "reused");
      assert.equal(fetchCount, 0);
    } finally {
      rmSync(home, { recursive: true, force: true });
    }
  });
});
