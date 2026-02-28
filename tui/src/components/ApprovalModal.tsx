import { Box, Text, useInput } from "ink";

import type { ApprovalDecision } from "../protocol/types.js";
import type { ApprovalRequest } from "../hooks/useApprovalQueue.js";

type ApprovalModalProps = {
  request: ApprovalRequest;
  onRespond: (decision: ApprovalDecision) => void;
};

export function approvalPreviewLines(request: ApprovalRequest): string[] {
  if (request.tool !== "shell") {
    return [`Preview: ${request.preview}`];
  }

  try {
    const parsed: unknown = JSON.parse(request.preview);
    if (typeof parsed !== "object" || parsed === null) {
      return [`Preview: ${request.preview}`];
    }

    const commandPreview = (parsed as { command_preview?: unknown }).command_preview;
    const timeoutMs = (parsed as { timeout_ms?: unknown }).timeout_ms;
    const lines: string[] = [];
    if (typeof commandPreview === "string" && commandPreview.length > 0) {
      lines.push(`Command: ${commandPreview}`);
    }
    if (typeof timeoutMs === "number") {
      lines.push(`Timeout: ${String(timeoutMs)}ms`);
    }
    if (lines.length > 0) {
      return lines;
    }
  } catch {
    return [`Preview: ${request.preview}`];
  }

  return [`Preview: ${request.preview}`];
}

export function decisionForApprovalKey(input: string): ApprovalDecision | null {
  const normalized = input.toLowerCase();
  if (normalized === "y") {
    return "approved";
  }
  if (normalized === "n") {
    return "denied";
  }
  if (normalized === "s") {
    return "approved_for_session";
  }
  if (normalized === "a") {
    return "abort";
  }
  return null;
}

export function ApprovalModal({ request, onRespond }: ApprovalModalProps) {
  const previewLines = approvalPreviewLines(request);

  useInput((input) => {
    const decision = decisionForApprovalKey(input);
    if (decision !== null) {
      onRespond(decision);
    }
  });

  return (
    <Box
      borderStyle="double"
      borderColor="yellow"
      flexDirection="column"
      paddingX={1}
      marginTop={1}
    >
      <Text color="yellow">Approval required</Text>
      <Text>{`Tool: ${request.tool}`}</Text>
      {previewLines.map((line) => (
        <Text key={line}>{line}</Text>
      ))}
      <Text dimColor>[y] approve [n] deny [s] session [a] abort</Text>
    </Box>
  );
}
