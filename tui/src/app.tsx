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
  hasPendingUserInput: boolean,
): boolean {
  const hasActiveTurn = turns.some((turn) => turn.status === "active");
  return hasActiveTurn || queueLength > 0 || hasPendingUserInput;
}

function summarizeUsageForTurns(
  turns: readonly TurnState[],
): {
  cumulativeUsage: TokenUsage | null;
  latestUsage: TokenUsage | null;
} {
  let latestUsage: TokenUsage | null = null;
  let cumulativeUsage: TokenUsage | null = null;

  for (const turn of turns) {
    if (turn.usage === null) {
      continue;
    }

    latestUsage = turn.usage.turn;
    cumulativeUsage = turn.usage.cumulative;
  }

  return {
    cumulativeUsage,
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
  const {
    turns,
    threadId,
    hasPendingUserInput,
    pendingUserInputWarning,
    queueUserInput,
  } = useTurns(events);
  const { currentRequest, decisionLog, queueLength, respond } = useApprovalQueue(events, writer);

  const isBusy = turns.some((turn) => turn.status === "active");
  const inputDisabled = isInputDisabled(turns, queueLength, hasPendingUserInput);
  const usageSummary = summarizeUsageForTurns(turns);

  const handleSubmit = useCallback(
    (text: string): void => {
      if (inputDisabled) {
        return;
      }
      const queued = queueUserInput(text);
      if (!queued) {
        return;
      }
      writer.sendUserInput(text);
    },
    [inputDisabled, queueUserInput, writer],
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
          pendingUserInputWarning={pendingUserInputWarning}
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
