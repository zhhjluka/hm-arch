import { createHash } from "node:crypto";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { DEFAULT_DB_FILENAME, DEFAULT_MAX_CONTEXT_CHARS, DEFAULT_REQUEST_TIMEOUT_MS, DEFAULT_TOP_K, } from "./types.js";
export function readPluginConfig(api) {
    const raw = (api.pluginConfig ?? api.config ?? {});
    return raw;
}
export function resolveDbPath(pluginConfig, openclawRoot = process.cwd()) {
    const stateDir = process.env.OPENCLAW_STATE_DIR?.trim() || join(homedir(), ".openclaw");
    const raw = pluginConfig.dbPath?.trim();
    if (!raw) {
        return join(openclawRoot, DEFAULT_DB_FILENAME);
    }
    const expanded = raw
        .replaceAll("$OPENCLAW_STATE_DIR", stateDir)
        .replaceAll("${OPENCLAW_STATE_DIR}", stateDir)
        .replace(/^~(?=$|[\\/])/, homedir());
    const candidate = resolve(expanded.startsWith("~") ? expanded : expanded);
    if (!candidate.startsWith("/") && !/^[A-Za-z]:[\\/]/.test(candidate)) {
        return resolve(openclawRoot, candidate);
    }
    return candidate;
}
export function resolveSidecarCommand(pluginConfig) {
    if (Array.isArray(pluginConfig.sidecarCommand) && pluginConfig.sidecarCommand.length > 0) {
        return pluginConfig.sidecarCommand.map(String);
    }
    return ["hm-arch", "openclaw", "sidecar"];
}
export function resolveTopK(pluginConfig) {
    return pluginConfig.topK && pluginConfig.topK > 0
        ? pluginConfig.topK
        : DEFAULT_TOP_K;
}
export function resolveMaxContextChars(pluginConfig) {
    return pluginConfig.maxContextChars && pluginConfig.maxContextChars > 0
        ? pluginConfig.maxContextChars
        : DEFAULT_MAX_CONTEXT_CHARS;
}
export function resolveRequestTimeoutMs(pluginConfig) {
    return pluginConfig.requestTimeoutMs && pluginConfig.requestTimeoutMs > 0
        ? pluginConfig.requestTimeoutMs
        : DEFAULT_REQUEST_TIMEOUT_MS;
}
export function fingerprintTurn(sessionId, userMessage, agentMessage) {
    const digest = createHash("sha256");
    digest.update(sessionId);
    digest.update("\0");
    digest.update(userMessage.trim());
    digest.update("\0");
    digest.update(agentMessage.trim());
    return digest.digest("hex");
}
//# sourceMappingURL=config.js.map