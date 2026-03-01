import { useState } from "react";
import { Box, Text, useInput } from "ink";

import type { ApprovalDecisionLog } from "../hooks/useApprovalQueue.js";
import type { ToolCallState, TurnState } from "../hooks/useTurns.js";
import type { ApprovalPolicyValue } from "../runtime/launch.js";
import { Spinner } from "./Spinner.js";
import { ToolCallPanel } from "./ToolCallPanel.js";

const VISIBLE_TURNS = 20;

type ChatViewProps = {
  approvalDecisionLog?: readonly ApprovalDecisionLog[];
  approvalPolicy?: ApprovalPolicyValue;
  pendingUserInputWarning?: string | null;
  showToolCallSummary?: boolean;
  turns: TurnState[];
};

export function ChatView({
  approvalDecisionLog = [],
  approvalPolicy = "on-request",
  pendingUserInputWarning = null,
  showToolCallSummary = false,
  turns,
}: ChatViewProps) {
  const [showToolDetails, setShowToolDetails] = useState(false);

  useInput((input, key) => {
    if (key.ctrl && input.toLowerCase() === "o") {
      setShowToolDetails((current) => !current);
    }
  });

  const hiddenTurnCount = Math.max(0, turns.length - VISIBLE_TURNS);
  const visibleTurns = turns.slice(-VISIBLE_TURNS);

  return (
    <Box flexDirection="column">
      {pendingUserInputWarning !== null ? (
        <Text color="yellow">{`Warning: ${pendingUserInputWarning}`}</Text>
      ) : null}
      {hiddenTurnCount > 0 ? (
        <Text dimColor>{`... ${String(hiddenTurnCount)} earlier turns hidden`}</Text>
      ) : null}
      {visibleTurns.map((turn) => (
        <TurnRow
          approvalDecisionLog={approvalDecisionLog}
          approvalPolicy={approvalPolicy}
          key={turn.turn_id}
          showToolDetails={showToolDetails}
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
  showToolDetails: boolean;
  showToolCallSummary: boolean;
  turn: TurnState;
};

type TurnRenderSection = "user" | "tool" | "assistant";

export function formatUserMessageLines(text: string): string[] {
  return text.split("\n").map((line) => `> ${line}`);
}

export function formatAssistantMessageLines(lines: readonly string[]): string[] {
  const [first, ...rest] = lines;
  if (first === undefined) {
    return [];
  }
  return [`• ${first}`, ...rest.map((line) => `  ${line}`)];
}

export function renderSectionsForTurn(
  turn: Pick<TurnState, "assistantLines" | "partialLine" | "toolCalls" | "userText">,
): TurnRenderSection[] {
  const sections: TurnRenderSection[] = [];
  if (turn.userText.length > 0) {
    sections.push("user");
  }
  if (Object.values(turn.toolCalls).length > 0) {
    sections.push("tool");
  }
  if (turn.assistantLines.length > 0 || turn.partialLine.length > 0) {
    sections.push("assistant");
  }
  return sections;
}

export function toolCallsInDisplayOrder(turn: TurnState): ToolCallState[] {
  return Object.values(turn.toolCalls);
}

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
  showToolDetails,
  showToolCallSummary,
  turn,
}: TurnRowProps) {
  const toolCalls = toolCallsInDisplayOrder(turn);
  const userLines =
    turn.userText.length > 0 ? formatUserMessageLines(turn.userText) : [];
  const assistantLines = [...turn.assistantLines];
  if (turn.partialLine.length > 0) {
    assistantLines.push(turn.partialLine);
  }
  const assistantDisplayLines = formatAssistantMessageLines(assistantLines);
  const sectionOrder = renderSectionsForTurn(turn);
  const toolCallSummary = showToolCallSummary
    ? summarizeToolCallsForTurn(turn)
    : null;
  const approvalDebugLines = showToolCallSummary
    ? summarizeApprovalDebugLinesForTurn(turn, approvalDecisionLog, approvalPolicy)
    : [];

  return (
    <Box flexDirection="column" marginBottom={1}>
      {sectionOrder.map((section, sectionIndex) => (
        <Box
          flexDirection="column"
          key={`${turn.turn_id}:section:${section}`}
          marginTop={sectionIndex > 0 ? 1 : 0}
        >
          {section === "user"
            ? userLines.map((line, index) => (
                <Text
                  backgroundColor="blackBright"
                  color="white"
                  key={`${turn.turn_id}:user:${String(index)}`}
                >
                  {` ${line} `}
                </Text>
              ))
            : null}

          {section === "tool"
            ? toolCalls.map((toolCall) => (
                <ToolCallPanel
                  key={toolCall.item_id}
                  showDetails={showToolDetails}
                  toolCall={toolCall}
                />
              ))
            : null}

          {section === "assistant"
            ? assistantDisplayLines.map((line, index) => (
                <Text key={`${turn.turn_id}:assistant:${String(index)}`}>{line}</Text>
              ))
            : null}
        </Box>
      ))}

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
