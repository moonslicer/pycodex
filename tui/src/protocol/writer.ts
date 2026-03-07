import type { ApprovalDecision } from "./types.js";

export interface ProtocolWriter {
  sendUserInput(text: string): void;
  sendApprovalResponse(requestId: string, decision: ApprovalDecision): void;
  sendInterrupt(): void;
  sendSessionResume(threadId: string): void;
  sendSessionNew(): void;
  close(): void;
}
