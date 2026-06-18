import { fingerprintTurn } from "./config.js";

export class TurnCaptureTracker {
  private readonly seen = new Set<string>();

  shouldCapture(sessionId: string, userMessage: string, agentMessage: string): boolean {
    const fingerprint = fingerprintTurn(sessionId, userMessage, agentMessage);
    if (this.seen.has(fingerprint)) {
      return false;
    }
    this.seen.add(fingerprint);
    return true;
  }

  clear(): void {
    this.seen.clear();
  }
}

export function extractLatestTurn(messages: Array<{ role?: string; content?: string }> | undefined): {
  userMessage: string;
  agentMessage: string;
} {
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
    } else if (role === "assistant" || role === "agent") {
      agentMessage = content;
    }
  }
  return { userMessage, agentMessage };
}

export function extractPromptText(event: Record<string, unknown>): string {
  if (typeof event.prompt === "string" && event.prompt.trim()) {
    return event.prompt.trim();
  }
  if (typeof event.userMessage === "string" && event.userMessage.trim()) {
    return event.userMessage.trim();
  }
  const messages = event.messages as Array<{ role?: string; content?: string }> | undefined;
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
