import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

export function sha256Buffer(data: Buffer): string {
  return createHash("sha256").update(data).digest("hex");
}

export function sha256File(path: string): string {
  const data = readFileSync(path);
  return sha256Buffer(data);
}

/** Parse ``<digest>  <filename>`` lines from a ``.sha256`` sidecar or SHA256SUMS. */
export function parseSha256Line(
  line: string,
): { digest: string; filename: string } | null {
  const stripped = line.trim();
  if (!stripped) {
    return null;
  }
  const spaceIndex = stripped.indexOf(" ");
  if (spaceIndex < 0) {
    return null;
  }
  const digest = stripped.slice(0, spaceIndex);
  const filename = stripped.slice(spaceIndex + 1).trim();
  if (!/^[a-f0-9]{64}$/i.test(digest) || !filename) {
    return null;
  }
  return { digest: digest.toLowerCase(), filename };
}

export function verifySha256Digest(
  actualDigest: string,
  expectedDigest: string,
  label: string,
): void {
  const actual = actualDigest.toLowerCase();
  const expected = expectedDigest.toLowerCase();
  if (actual !== expected) {
    throw new Error(
      `Checksum mismatch for ${label}: expected ${expected}, got ${actual}`,
    );
  }
}

export function verifySha256Sidecar(
  artifactBytes: Buffer,
  sidecarText: string,
  expectedFilename: string,
): void {
  const parsed = parseSha256Line(sidecarText.split("\n")[0] ?? "");
  if (!parsed) {
    throw new Error(`Invalid checksum sidecar for ${expectedFilename}`);
  }
  if (parsed.filename !== expectedFilename) {
    throw new Error(
      `Checksum filename mismatch: ${parsed.filename} != ${expectedFilename}`,
    );
  }
  verifySha256Digest(sha256Buffer(artifactBytes), parsed.digest, expectedFilename);
}
