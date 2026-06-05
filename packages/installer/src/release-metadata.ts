import type { ReleaseArch, ReleaseOs, ReleaseTarget } from "./release-target.js";
import { artifactSuffix, releaseArtifactFilename } from "./release-target.js";

export type ReleaseArtifactRecord = {
  filename: string;
  os: ReleaseOs;
  arch: ReleaseArch;
  version: string;
  sha256: string;
  size_bytes: number;
};

export type StandaloneReleaseMetadata = {
  schema_version: number;
  package: string;
  version: string;
  generated_at?: string;
  artifacts: ReleaseArtifactRecord[];
};

export function parseReleaseMetadata(text: string): StandaloneReleaseMetadata {
  let payload: unknown;
  try {
    payload = JSON.parse(text);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`Invalid release metadata JSON: ${message}`);
  }
  return validateReleaseMetadata(payload);
}

export function validateReleaseMetadata(payload: unknown): StandaloneReleaseMetadata {
  if (!payload || typeof payload !== "object") {
    throw new Error("Release metadata must be a JSON object");
  }
  const record = payload as Record<string, unknown>;
  if (record.schema_version !== 1) {
    throw new Error(`Unsupported release metadata schema_version: ${record.schema_version}`);
  }
  if (record.package !== "hm-arch") {
    throw new Error(`Unexpected release metadata package: ${record.package}`);
  }
  if (typeof record.version !== "string" || !record.version) {
    throw new Error("Release metadata is missing version");
  }
  if (!Array.isArray(record.artifacts) || record.artifacts.length === 0) {
    throw new Error("Release metadata has no artifacts");
  }

  const artifacts: ReleaseArtifactRecord[] = [];
  for (const item of record.artifacts) {
    artifacts.push(validateArtifactRecord(item, record.version));
  }

  return {
    schema_version: 1,
    package: "hm-arch",
    version: record.version,
    generated_at: typeof record.generated_at === "string" ? record.generated_at : undefined,
    artifacts,
  };
}

function validateArtifactRecord(item: unknown, metadataVersion: string): ReleaseArtifactRecord {
  if (!item || typeof item !== "object") {
    throw new Error("Invalid artifact record in release metadata");
  }
  const record = item as Record<string, unknown>;
  const filename = record.filename;
  const os = record.os;
  const arch = record.arch;
  const version = record.version;
  const sha256 = record.sha256;
  const sizeBytes = record.size_bytes;

  if (typeof filename !== "string" || !filename) {
    throw new Error("Artifact record missing filename");
  }
  if (os !== "linux" && os !== "darwin" && os !== "windows") {
    throw new Error(`Artifact record has invalid os: ${os}`);
  }
  if (arch !== "x86_64" && arch !== "aarch64" && arch !== "arm64") {
    throw new Error(`Artifact record has invalid arch: ${arch}`);
  }
  if (typeof version !== "string" || version !== metadataVersion) {
    throw new Error(`Artifact version mismatch for ${filename}`);
  }
  if (typeof sha256 !== "string" || !/^[a-f0-9]{64}$/i.test(sha256)) {
    throw new Error(`Artifact record has invalid sha256 for ${filename}`);
  }
  if (typeof sizeBytes !== "number" || !Number.isFinite(sizeBytes) || sizeBytes < 0) {
    throw new Error(`Artifact record has invalid size_bytes for ${filename}`);
  }

  const expectedFilename = releaseArtifactFilename(version, { os, arch });
  if (filename !== expectedFilename) {
    throw new Error(
      `Artifact filename does not match target: ${filename} != ${expectedFilename}`,
    );
  }

  return {
    filename,
    os,
    arch,
    version,
    sha256: sha256.toLowerCase(),
    size_bytes: sizeBytes,
  };
}

export function findArtifactForTarget(
  metadata: StandaloneReleaseMetadata,
  target: ReleaseTarget,
): ReleaseArtifactRecord {
  const suffix = artifactSuffix(target);
  const match = metadata.artifacts.find(
    (artifact) => artifact.os === target.os && artifact.arch === target.arch,
  );
  if (!match) {
    throw new Error(`Release metadata has no artifact for ${suffix}`);
  }
  return match;
}
