import { useCallback } from "react";
import { Box } from "ink";

import type { ApprovalPolicyValue } from "./runtime/launch.js";
import { ApprovalModal } from "./components/ApprovalModal.js";
import { ChatView } from "./components/ChatView.js";
import { InputArea } from "./components/InputArea.js";
import { StatusBar } from "./components/StatusBar.js";
import type { TurnState } from "./hooks/useTurns.js";
import type { TokenUsage } from "./protocol/types.js";
import { useApprovalQueue } from "./hooks/useApprovalQueue.js";
import { useProtocolEvents } from "./hooks/useProtocolEvents.js";
import { useTurns } from "./hooks/useTurns.js";
import type { ProtocolReader } from "./protocol/reader.js";
import type { ProtocolWriter } from "./protocol/writer.js";

type AppProps = {
  approvalPolicy?: ApprovalPolicyValue;
  debug?: boolean;
  onExitRequested: () => void;
  reader: ProtocolReader;
  writer: ProtocolWriter;
};

export function isInputDisabled(
  turns: readonly TurnState[],
  queueLength: number,
): boolean {
  const hasActiveTurn = turns.some((turn) => turn.status === "active");
  return hasActiveTurn || queueLength > 0;
}

export function summarizeUsageForTurns(
  turns: readonly TurnState[],
): {
  cumulativeUsage: TokenUsage | null;
  latestUsage: TokenUsage | null;
} {
  let latestUsage: TokenUsage | null = null;
  let totalInputTokens = 0;
  let totalOutputTokens = 0;
  let hasUsage = false;

  for (const turn of turns) {
    if (turn.usage === null) {
      continue;
    }

    latestUsage = turn.usage;
    totalInputTokens += turn.usage.input_tokens;
    totalOutputTokens += turn.usage.output_tokens;
    hasUsage = true;
  }

  return {
    cumulativeUsage: hasUsage
      ? {
          input_tokens: totalInputTokens,
          output_tokens: totalOutputTokens,
        }
      : null,
    latestUsage,
  };
}

export function App({
  approvalPolicy = "on-request",
  debug = false,
  onExitRequested,
  reader,
  writer,
}: AppProps) {
  const { events } = useProtocolEvents(reader);
  const { turns, threadId, setUserText } = useTurns(events);
  const { currentRequest, decisionLog, queueLength, respond } = useApprovalQueue(events, writer);

  const isBusy = turns.some((turn) => turn.status === "active");
  const inputDisabled = isInputDisabled(turns, queueLength);
  const usageSummary = summarizeUsageForTurns(turns);

  // Find the active turn_id so we can stamp userText before sending.
  const activeTurnId = turns.find((t) => t.status === "active")?.turn_id;

  const handleSubmit = useCallback(
    (text: string): void => {
      if (inputDisabled) {
        return;
      }
      if (activeTurnId !== undefined) {
        setUserText(activeTurnId, text);
      }
      writer.sendUserInput(text);
    },
    [activeTurnId, inputDisabled, setUserText, writer],
  );

  const handleInterrupt = useCallback((): void => {
    writer.sendInterrupt();
  }, [writer]);

  return (
    <Box flexDirection="column">
      <Box flexDirection="column" flexGrow={1}>
        <ChatView
          approvalDecisionLog={decisionLog}
          approvalPolicy={approvalPolicy}
          showToolCallSummary={debug}
          turns={turns}
        />
      </Box>
      {currentRequest !== null ? (
        <ApprovalModal onRespond={respond} request={currentRequest} />
      ) : null}
      <InputArea
        disabled={inputDisabled}
        hasActiveTurn={isBusy}
        onExit={onExitRequested}
        onInterrupt={handleInterrupt}
        onSubmit={handleSubmit}
      />
      <StatusBar
        cumulativeUsage={usageSummary.cumulativeUsage}
        isBusy={isBusy}
        latestUsage={usageSummary.latestUsage}
        threadId={threadId}
        turnCount={turns.length}
      />
    </Box>
  );
}
