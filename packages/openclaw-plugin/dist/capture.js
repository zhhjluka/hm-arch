import { fingerprintTurn } from "./config.js";
export class TurnCaptureTracker {
    seen = new Set();
    shouldCapture(sessionId, userMessage, agentMessage) {
        const fingerprint = fingerprintTurn(sessionId, userMessage, agentMessage);
        if (this.seen.has(fingerprint)) {
            return false;
        }
        this.seen.add(fingerprint);
        return true;
    }
    clear() {
        this.seen.clear();
    }
}
export function extractLatestTurn(messages) {
    if (!messages || messages.length === 0) {
        return { userMessage: "", agentMessage: "" };
    }
    let userMessage = "";
    let agentMessage = "";
    for (const message of messages) {
        const role = (message.role ?? "").toLowerCase();
        const content = typeof message.content === "string" ? message.content : "";
        if (role === "user") {
            userMessage = content;
        }
        else if (role === "assistant" || role === "agent") {
            agentMessage = content;
        }
    }
    return { userMessage, agentMessage };
}
export function extractPromptText(event) {
    if (typeof event.prompt === "string" && event.prompt.trim()) {
        return event.prompt.trim();
    }
    if (typeof event.userMessage === "string" && event.userMessage.trim()) {
        return event.userMessage.trim();
    }
    const messages = event.messages;
    if (messages) {
        for (let index = messages.length - 1; index >= 0; index -= 1) {
            const message = messages[index];
            if ((message.role ?? "").toLowerCase() === "user") {
                const content = typeof message.content === "string" ? message.content.trim() : "";
                if (content) {
                    return content;
                }
            }
        }
    }
    return "";
}
//# sourceMappingURL=capture.js.map