import { extractLatestAssistantText, extractLatestUserText, formatRecallContext, messageFingerprint, normalizeRecallQuery, resolveAutoCaptureStartIndex, } from "./messages.js";
export async function runBeforePromptBuild(controllers, event) {
    if (!controllers.config.autoRecall) {
        return undefined;
    }
    const messages = Array.isArray(event.messages) ? event.messages : [];
    const querySource = extractLatestUserText(messages) ??
        (typeof event.prompt === "string" ? event.prompt : "");
    const query = normalizeRecallQuery(querySource, controllers.config.maxContextChars);
    if (query.length < 2) {
        return undefined;
    }
    try {
        const response = await controllers.sidecar.search({
            query,
            topK: controllers.config.topK,
            maxContextChars: controllers.config.maxContextChars,
        });
        if (!response.ok) {
            controllers.logger.warn?.(`memory-hm-arch: auto-recall failed: ${response.error?.message ?? "unknown error"}`);
            return undefined;
        }
        const context = typeof response.result.context === "string" ? response.result.context : "";
        const formatted = formatRecallContext(context);
        if (!formatted) {
            return undefined;
        }
        controllers.logger.info?.("memory-hm-arch: injecting recalled memory into context");
        return { prependContext: formatted };
    }
    catch (error) {
        controllers.logger.warn?.(`memory-hm-arch: auto-recall failed: ${String(error)}`);
        return undefined;
    }
}
export async function runAgentEnd(controllers, event, ctx) {
    if (!controllers.config.autoCapture) {
        return;
    }
    if (!event.success || !Array.isArray(event.messages) || event.messages.length === 0) {
        return;
    }
    const cursorKey = ctx.sessionKey ?? ctx.sessionId;
    const startIndex = resolveAutoCaptureStartIndex(event.messages, cursorKey ? controllers.captureCursors.get(cursorKey) : undefined);
    const userMessage = extractLatestUserText(event.messages.slice(startIndex));
    const agentMessage = extractLatestAssistantText(event.messages.slice(startIndex));
    if (!userMessage && !agentMessage) {
        return;
    }
    try {
        const response = await controllers.sidecar.recordTurn({
            userMessage,
            agentMessage,
            sessionId: ctx.sessionId,
        });
        if (!response.ok) {
            controllers.logger.warn?.(`memory-hm-arch: auto-capture failed: ${response.error?.message ?? "unknown error"}`);
            return;
        }
        if (cursorKey) {
            const lastMessage = event.messages[event.messages.length - 1];
            controllers.captureCursors.set(cursorKey, {
                nextIndex: event.messages.length,
                lastMessageFingerprint: messageFingerprint(lastMessage),
            });
        }
        const recorded = response.result.recorded_count;
        if (typeof recorded === "number" && recorded > 0) {
            controllers.logger.info?.(`memory-hm-arch: auto-captured ${recorded} turn fragment(s)`);
        }
    }
    catch (error) {
        controllers.logger.warn?.(`memory-hm-arch: auto-capture failed: ${String(error)}`);
    }
}
export async function runSessionEnd(controllers, event, ctx) {
    const cursorKey = ctx.sessionKey ?? event.sessionKey ?? ctx.sessionId ?? event.sessionId;
    controllers.captureCursors.delete(cursorKey);
    const nextCursorKey = event.nextSessionKey ?? event.nextSessionId;
    if (nextCursorKey) {
        controllers.captureCursors.delete(nextCursorKey);
    }
    if (!controllers.config.consolidateOnSessionEnd) {
        return;
    }
    const reason = event.reason ?? "unknown";
    if (reason !== "idle" && reason !== "shutdown" && reason !== "restart") {
        return;
    }
    try {
        await controllers.sidecar.consolidate({
            force: false,
            sessionId: ctx.sessionId ?? event.sessionId,
        });
    }
    catch (error) {
        controllers.logger.warn?.(`memory-hm-arch: session consolidation failed: ${String(error)}`);
    }
}
//# sourceMappingURL=hooks.js.map