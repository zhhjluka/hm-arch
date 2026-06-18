export declare class TurnCaptureTracker {
    private readonly seen;
    shouldCapture(sessionId: string, userMessage: string, agentMessage: string): boolean;
    clear(): void;
}
export declare function extractLatestTurn(messages: Array<{
    role?: string;
    content?: string;
}> | undefined): {
    userMessage: string;
    agentMessage: string;
};
export declare function extractPromptText(event: Record<string, unknown>): string;
//# sourceMappingURL=capture.d.ts.map