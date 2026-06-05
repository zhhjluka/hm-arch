import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";

import { BUNDLED_HM_ARCH_VERSION } from "./bundled-version.js";
import {
  DEFAULT_GITHUB_REPO,
  ENV_HM_ARCH_RELEASE_BASE_URL,
  ENV_HM_ARCH_RUNTIME,
} from "./constants.js";
import {
  sha256Buffer,
  verifySha256Digest,
  verifySha256Sidecar,
} from "./integrity.js";
import {
  findArtifactForTarget,
  parseReleaseMetadata,
  type ReleaseArtifactRecord,
  type StandaloneReleaseMetadata,
} from "./release-metadata.js";
import {
  detectReleaseTarget,
  releaseArtifactFilename,
  type ReleaseTarget,
  unsupportedReleaseTargetDiagnostic,
} from "./release-target.js";
import {
  managedStandaloneExecutable,
  managedStandaloneStatePath,
  resolveHmArchHome,
  standaloneBinaryRoot,
} from "./paths.js";

export type StandaloneBinaryState = {
  hmArchVersion: string;
  targetOs: string;
  targetArch: string;
  filename: string;
  sha256: string;
  sizeBytes: number;
  installerVersion: string;
  createdAt: string;
  updatedAt: string;
};

export type StandaloneBinaryStatus = {
  home: string;
  root: string;
  executable: string;
  state: StandaloneBinaryState | null;
  ready: boolean;
};

export type EnsureStandaloneBinaryResult = {
  home: string;
  root: string;
  executable: string;
  state: StandaloneBinaryState;
  action: "created" | "reused" | "upgraded";
};

export type StandaloneBinaryDeps = {
  hmArchHome?: string;
  targetVersion?: string;
  releaseBaseUrl?: string;
  githubRepo?: string;
  target?: ReleaseTarget;
  now?: () => string;
  exists?: (path: string) => boolean;
  mkdir?: (path: string) => void;
  chmod?: (path: string, mode: number) => void;
  readState?: (home: string) => StandaloneBinaryState | null;
  writeState?: (home: string, state: StandaloneBinaryState) => void;
  fetchText?: (url: string) => Promise<string>;
  fetchBuffer?: (url: string) => Promise<Buffer>;
  readFile?: (path: string) => Buffer;
  writeFile?: (path: string, data: Buffer) => void;
};

const INSTALLER_VERSION = "1.0.0";

function defaultNow(): string {
  return new Date().toISOString();
}

function defaultExists(path: string): boolean {
  return existsSync(path);
}

function defaultMkdir(path: string): void {
  mkdirSync(path, { recursive: true });
}

function defaultChmod(path: string, mode: number): void {
  chmodSync(path, mode);
}

function defaultWriteFile(path: string, data: Buffer): void {
  writeFileSync(path, data);
}

function defaultReadFile(path: string): Buffer {
  return readFileSync(path);
}

async function defaultFetchText(url: string): Promise<string> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} fetching ${url}`);
  }
  return response.text();
}

async function defaultFetchBuffer(url: string): Promise<Buffer> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} fetching ${url}`);
  }
  const arrayBuffer = await response.arrayBuffer();
  return Buffer.from(arrayBuffer);
}

export function resolveReleaseBaseUrl(deps: StandaloneBinaryDeps = {}): string {
  const fromEnv = process.env[ENV_HM_ARCH_RELEASE_BASE_URL];
  if (deps.releaseBaseUrl) {
    return deps.releaseBaseUrl.replace(/\/$/, "");
  }
  if (fromEnv) {
    return fromEnv.replace(/\/$/, "");
  }
  const repo = deps.githubRepo ?? DEFAULT_GITHUB_REPO;
  return `https://github.com/${repo}/releases/download`;
}

export function releaseDownloadUrl(
  baseUrl: string,
  version: string,
  filename: string,
): string {
  return `${baseUrl}/v${version}/${filename}`;
}

export function readStandaloneBinaryState(
  hmArchHome: string,
  deps: Pick<StandaloneBinaryDeps, "exists" | "readState"> = {},
): StandaloneBinaryState | null {
  if (deps.readState) {
    return deps.readState(hmArchHome);
  }
  const exists = deps.exists ?? defaultExists;
  const statePath = managedStandaloneStatePath(hmArchHome);
  if (!exists(statePath)) {
    return null;
  }
  try {
    return JSON.parse(readFileSync(statePath, "utf8")) as StandaloneBinaryState;
  } catch {
    return null;
  }
}

export function writeStandaloneBinaryState(
  hmArchHome: string,
  state: StandaloneBinaryState,
  deps: Pick<StandaloneBinaryDeps, "mkdir" | "writeState"> = {},
): void {
  if (deps.writeState) {
    deps.writeState(hmArchHome, state);
    return;
  }
  const mkdir = deps.mkdir ?? defaultMkdir;
  const statePath = managedStandaloneStatePath(hmArchHome);
  mkdir(standaloneBinaryRoot(hmArchHome));
  writeFileSync(statePath, `${JSON.stringify(state, null, 2)}\n`, "utf8");
}

export function describeStandaloneBinary(deps: StandaloneBinaryDeps = {}): StandaloneBinaryStatus {
  const home = deps.hmArchHome ?? resolveHmArchHome();
  const exists = deps.exists ?? defaultExists;
  const executable = managedStandaloneExecutable(home);
  const state = readStandaloneBinaryState(home, deps);
  const ready = exists(executable) && state !== null;
  return {
    home,
    root: standaloneBinaryRoot(home),
    executable,
    state,
    ready,
  };
}

function buildState(
  record: ReleaseArtifactRecord,
  target: ReleaseTarget,
  previous: StandaloneBinaryState | null,
  now: string,
): StandaloneBinaryState {
  return {
    hmArchVersion: record.version,
    targetOs: target.os,
    targetArch: target.arch,
    filename: record.filename,
    sha256: record.sha256,
    sizeBytes: record.size_bytes,
    installerVersion: INSTALLER_VERSION,
    createdAt: previous?.createdAt ?? now,
    updatedAt: now,
  };
}

export function verifyDownloadedArtifact(
  bytes: Buffer,
  record: ReleaseArtifactRecord,
  checksumSidecar: string | null,
): void {
  const digest = sha256Buffer(bytes);
  verifySha256Digest(digest, record.sha256, record.filename);
  if (bytes.length !== record.size_bytes) {
    throw new Error(
      `Size mismatch for ${record.filename}: expected ${record.size_bytes}, got ${bytes.length}`,
    );
  }
  if (checksumSidecar !== null) {
    verifySha256Sidecar(bytes, checksumSidecar, record.filename);
  }
}

export function verifyReleaseMetadataSignature(
  metadata: StandaloneReleaseMetadata,
  expectedVersion: string,
): void {
  if (metadata.package !== "hm-arch") {
    throw new Error(`Unexpected release package: ${metadata.package}`);
  }
  if (metadata.version !== expectedVersion) {
    throw new Error(
      `Release metadata version mismatch: ${metadata.version} != ${expectedVersion}`,
    );
  }
}

export async function downloadVerifiedStandaloneArtifact(
  options: {
    version: string;
    target: ReleaseTarget;
  },
  deps: StandaloneBinaryDeps = {},
): Promise<{ bytes: Buffer; record: ReleaseArtifactRecord; metadata: StandaloneReleaseMetadata }> {
  const baseUrl = resolveReleaseBaseUrl(deps);
  const fetchText = deps.fetchText ?? defaultFetchText;
  const fetchBuffer = deps.fetchBuffer ?? defaultFetchBuffer;
  const metadataFilename = `hm-arch-${options.version}-standalone-release-metadata.json`;
  const metadataUrl = releaseDownloadUrl(baseUrl, options.version, metadataFilename);
  const metadata = parseReleaseMetadata(await fetchText(metadataUrl));
  verifyReleaseMetadataSignature(metadata, options.version);
  const record = findArtifactForTarget(metadata, options.target);
  const artifactUrl = releaseDownloadUrl(baseUrl, options.version, record.filename);
  const checksumUrl = `${artifactUrl}.sha256`;
  const bytes = await fetchBuffer(artifactUrl);
  let checksumSidecar: string | null = null;
  try {
    checksumSidecar = await fetchText(checksumUrl);
  } catch {
    checksumSidecar = null;
  }
  verifyDownloadedArtifact(bytes, record, checksumSidecar);
  return { bytes, record, metadata };
}

function standaloneInstallReady(
  hmArchHome: string,
  targetVersion: string,
  target: ReleaseTarget,
  exists: (path: string) => boolean,
  state: StandaloneBinaryState | null,
): boolean {
  const executable = managedStandaloneExecutable(hmArchHome);
  if (!exists(executable) || !state) {
    return false;
  }
  return (
    state.hmArchVersion === targetVersion &&
    state.targetOs === target.os &&
    state.targetArch === target.arch
  );
}

/**
 * Download (when needed), verify checksums and release metadata, and install the
 * standalone hm-arch executable under {@link resolveHmArchHome}.
 */
export async function ensureStandaloneBinary(
  options: { upgrade?: boolean } = {},
  deps: StandaloneBinaryDeps = {},
): Promise<EnsureStandaloneBinaryResult> {
  const exists = deps.exists ?? defaultExists;
  const now = (deps.now ?? defaultNow)();
  const home = deps.hmArchHome ?? resolveHmArchHome();
  const target = deps.target ?? detectReleaseTarget();
  if (!target) {
    const diagnostic = unsupportedReleaseTargetDiagnostic();
    throw new Error(diagnostic.message);
  }

  const targetVersion = deps.targetVersion ?? BUNDLED_HM_ARCH_VERSION;
  const previous = readStandaloneBinaryState(home, deps);
  const ready = standaloneInstallReady(home, targetVersion, target, exists, previous);
  if (ready && options.upgrade !== true) {
    return {
      home,
      root: standaloneBinaryRoot(home),
      executable: managedStandaloneExecutable(home),
      state: previous!,
      action: "reused",
    };
  }

  const { bytes, record } = await downloadVerifiedStandaloneArtifact(
    { version: targetVersion, target },
    deps,
  );

  const mkdir = deps.mkdir ?? defaultMkdir;
  const writeFile = deps.writeFile ?? defaultWriteFile;
  const chmod = deps.chmod ?? defaultChmod;
  const root = standaloneBinaryRoot(home);
  mkdir(home);
  mkdir(root);
  const executable = managedStandaloneExecutable(home);
  writeFile(executable, bytes);
  if (process.platform !== "win32") {
    chmod(executable, 0o755);
  }

  const state = buildState(record, target, previous, now);
  writeStandaloneBinaryState(home, state, deps);

  const action =
    previous === null ? "created" : previous.hmArchVersion !== targetVersion ? "upgraded" : "reused";

  return {
    home,
    root,
    executable,
    state,
    action,
  };
}

export function formatEnsureStandaloneResult(result: EnsureStandaloneBinaryResult): string {
  const verb =
    result.action === "created"
      ? "Installed"
      : result.action === "upgraded"
        ? "Upgraded"
        : "Reused";
  return [
    `${verb} standalone hm-arch binary.`,
    `  home: ${result.home}`,
    `  binary: ${result.executable}`,
    `  hm-arch: ${result.state.hmArchVersion}`,
    `  target: ${result.state.targetOs}-${result.state.targetArch}`,
  ].join("\n");
}

export function prefersStandaloneRuntime(): boolean {
  const mode = (process.env[ENV_HM_ARCH_RUNTIME] ?? "auto").toLowerCase();
  if (mode === "python") {
    return false;
  }
  if (mode === "standalone") {
    return true;
  }
  return detectReleaseTarget() !== null;
}

export function requiresStandaloneRuntime(): boolean {
  return (process.env[ENV_HM_ARCH_RUNTIME] ?? "").toLowerCase() === "standalone";
}

export function standaloneTargetAvailable(): boolean {
  return detectReleaseTarget() !== null;
}
