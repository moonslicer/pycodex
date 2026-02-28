import { Box, Text } from "ink";

import type { TurnState } from "../hooks/useTurns.js";
import { Spinner } from "./Spinner.js";

const VISIBLE_TURNS = 20;

type ChatViewProps = {
  showToolCallSummary?: boolean;
  turns: TurnState[];
};

export function ChatView({ showToolCallSummary = false, turns }: ChatViewProps) {
  const hiddenTurnCount = Math.max(0, turns.length - VISIBLE_TURNS);
  const visibleTurns = turns.slice(-VISIBLE_TURNS);

  return (
    <Box flexDirection="column">
      {hiddenTurnCount > 0 ? (
        <Text dimColor>{`... ${String(hiddenTurnCount)} earlier turns hidden`}</Text>
      ) : null}
      {visibleTurns.map((turn) => (
        <TurnRow
          key={turn.turn_id}
          showToolCallSummary={showToolCallSummary}
          turn={turn}
        />
      ))}
    </Box>
  );
}

type TurnRowProps = {
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

function TurnRow({ showToolCallSummary, turn }: TurnRowProps) {
  const assistantLines = [...turn.assistantLines];
  if (turn.partialLine.length > 0) {
    assistantLines.push(turn.partialLine);
  }
  const assistantText = assistantLines.join("\n");
  const toolCallSummary = showToolCallSummary
    ? summarizeToolCallsForTurn(turn)
    : null;

  return (
    <Box flexDirection="column" marginBottom={1}>
      {turn.userText.length > 0 ? (
        <Text color="cyan">{`User: ${turn.userText}`}</Text>
      ) : null}

      {assistantText.length > 0 ? <Text>{assistantText}</Text> : null}

      {toolCallSummary !== null ? <Text dimColor>{toolCallSummary}</Text> : null}

      {turn.status === "active" ? (
        <Spinner label="Assistant is thinking" />
      ) : null}

      {turn.status === "failed" && turn.error !== null ? (
        <Text color="red">{`Error: ${turn.error}`}</Text>
      ) : null}
    </Box>
  );
}
