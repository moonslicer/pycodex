import { Box, Text } from "ink";

import type { ApprovalDecisionLog } from "../hooks/useApprovalQueue.js";
import type { TurnState } from "../hooks/useTurns.js";
import type { ApprovalPolicyValue } from "../runtime/launch.js";
import { Spinner } from "./Spinner.js";

const VISIBLE_TURNS = 20;

type ChatViewProps = {
  approvalDecisionLog?: readonly ApprovalDecisionLog[];
  approvalPolicy?: ApprovalPolicyValue;
  showToolCallSummary?: boolean;
  turns: TurnState[];
};

export function ChatView({
  approvalDecisionLog = [],
  approvalPolicy = "on-request",
  showToolCallSummary = false,
  turns,
}: ChatViewProps) {
  const hiddenTurnCount = Math.max(0, turns.length - VISIBLE_TURNS);
  const visibleTurns = turns.slice(-VISIBLE_TURNS);

  return (
    <Box flexDirection="column">
      {hiddenTurnCount > 0 ? (
        <Text dimColor>{`... ${String(hiddenTurnCount)} earlier turns hidden`}</Text>
      ) : null}
      {visibleTurns.map((turn) => (
        <TurnRow
          approvalDecisionLog={approvalDecisionLog}
          approvalPolicy={approvalPolicy}
          key={turn.turn_id}
          showToolCallSummary={showToolCallSummary}
          turn={turn}
        />
      ))}
    </Box>
  );
}

type TurnRowProps = {
  approvalDecisionLog: readonly ApprovalDecisionLog[];
  approvalPolicy: ApprovalPolicyValue;
  showToolCallSummary: boolean;
  turn: TurnState;
};

export function summarizeToolCallsForTurn(turn: TurnState): string | null {
  const namesInOrder: string[] = [];
  const seen = new Set<string>();
  for (const toolCall of Object.values(turn.toolCalls)) {
    if (seen.has(toolCall.name)) {
      continue;
    }
    seen.add(toolCall.name);
    namesInOrder.push(toolCall.name);
  }

  if (namesInOrder.length === 0) {
    return turn.status === "active" ? null : "No tool call this turn";
  }
  if (namesInOrder.length === 1) {
    const firstName = namesInOrder[0];
    if (firstName === undefined) {
      return null;
    }
    return `Tool called: ${firstName}`;
  }
  return `Tool calls: ${namesInOrder.join(", ")}`;
}

function decisionLabel(decision: ApprovalDecisionLog["decision"]): string {
  if (decision === "approved") {
    return "approved once";
  }
  if (decision === "approved_for_session") {
    return "approved for session";
  }
  if (decision === "denied") {
    return "denied";
  }
  return "aborted";
}

function shellCommandPreview(preview: string): string | null {
  try {
    const parsed: unknown = JSON.parse(preview);
    if (typeof parsed !== "object" || parsed === null) {
      return null;
    }
    const commandPreview = (parsed as { command_preview?: unknown }).command_preview;
    if (typeof commandPreview === "string" && commandPreview.length > 0) {
      return commandPreview;
    }
  } catch {
    return null;
  }
  return null;
}

export function summarizeApprovalDebugLinesForTurn(
  turn: TurnState,
  decisionLog: readonly ApprovalDecisionLog[],
  approvalPolicy: ApprovalPolicyValue,
): string[] {
  const lines: string[] = [];
  const logsForTurn = decisionLog.filter((entry) => entry.turn_id === turn.turn_id);
  for (const entry of logsForTurn) {
    const commandPreview = entry.tool === "shell" ? shellCommandPreview(entry.preview) : null;
    const objectLabel = commandPreview !== null
      ? `${entry.tool} command="${commandPreview}"`
      : entry.tool;
    lines.push(
      `Approval (${entry.source}): ${decisionLabel(entry.decision)} for ${objectLabel}`,
    );
  }

  if (turn.status === "active") {
    return lines;
  }

  const hasShellCall = Object.values(turn.toolCalls).some((toolCall) => toolCall.name === "shell");
  const hasShellPromptLog = logsForTurn.some((entry) => entry.tool === "shell");
  if (hasShellCall && !hasShellPromptLog) {
    if (approvalPolicy === "on-request" || approvalPolicy === "unless-trusted") {
      lines.push("Approval: no prompt for shell (likely session-cache hit)");
    } else {
      lines.push(`Approval: no prompt for shell (policy ${approvalPolicy})`);
    }
  }

  return lines;
}

function TurnRow({
  approvalDecisionLog,
  approvalPolicy,
  showToolCallSummary,
  turn,
}: TurnRowProps) {
  const assistantLines = [...turn.assistantLines];
  if (turn.partialLine.length > 0) {
    assistantLines.push(turn.partialLine);
  }
  const assistantText = assistantLines.join("\n");
  const toolCallSummary = showToolCallSummary
    ? summarizeToolCallsForTurn(turn)
    : null;
  const approvalDebugLines = showToolCallSummary
    ? summarizeApprovalDebugLinesForTurn(turn, approvalDecisionLog, approvalPolicy)
    : [];

  return (
    <Box flexDirection="column" marginBottom={1}>
      {turn.userText.length > 0 ? (
        <Text color="cyan">{`User: ${turn.userText}`}</Text>
      ) : null}

      {assistantText.length > 0 ? <Text>{assistantText}</Text> : null}

      {toolCallSummary !== null ? <Text dimColor>{toolCallSummary}</Text> : null}
      {approvalDebugLines.map((line) => (
        <Text dimColor key={`${turn.turn_id}:${line}`}>
          {line}
        </Text>
      ))}

      {turn.status === "active" ? (
        <Spinner label="Assistant is thinking" />
      ) : null}

      {turn.status === "failed" && turn.error !== null ? (
        <Text color="red">{`Error: ${turn.error}`}</Text>
      ) : null}
    </Box>
  );
}
