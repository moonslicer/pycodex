import { Box, Text } from "ink";

import type { TurnState } from "../hooks/useTurns.js";
import { Spinner } from "./Spinner.js";

const VISIBLE_TURNS = 20;

type ChatViewProps = {
  turns: TurnState[];
};

export function ChatView({ turns }: ChatViewProps) {
  const hiddenTurnCount = Math.max(0, turns.length - VISIBLE_TURNS);
  const visibleTurns = turns.slice(-VISIBLE_TURNS);

  return (
    <Box flexDirection="column">
      {hiddenTurnCount > 0 ? (
        <Text dimColor>{`... ${String(hiddenTurnCount)} earlier turns hidden`}</Text>
      ) : null}
      {visibleTurns.map((turn) => (
        <TurnRow key={turn.turn_id} turn={turn} />
      ))}
    </Box>
  );
}

type TurnRowProps = {
  turn: TurnState;
};

function TurnRow({ turn }: TurnRowProps) {
  const assistantLines = [...turn.assistantLines];
  if (turn.partialLine.length > 0) {
    assistantLines.push(turn.partialLine);
  }
  const assistantText = assistantLines.join("\n");

  return (
    <Box flexDirection="column" marginBottom={1}>
      {turn.userText.length > 0 ? (
        <Text color="cyan">{`User: ${turn.userText}`}</Text>
      ) : null}

      {assistantText.length > 0 ? <Text>{assistantText}</Text> : null}

      {turn.status === "active" ? (
        <Spinner label="Assistant is thinking" />
      ) : null}

      {turn.status === "failed" && turn.error !== null ? (
        <Text color="red">{`Error: ${turn.error}`}</Text>
      ) : null}
    </Box>
  );
}
