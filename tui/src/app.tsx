import { useCallback, useEffect, useRef, useState } from "react";
import { Box, Text } from "ink";

import type { ApprovalPolicyValue } from "./runtime/launch.js";
import { ApprovalModal } from "./components/ApprovalModal.js";
import { ChatView } from "./components/ChatView.js";
import { InputArea } from "./components/InputArea.js";
import { SessionPickerModal } from "./components/SessionPickerModal.js";
import { StatusBar } from "./components/StatusBar.js";
import type { TurnState } from "./hooks/useTurns.js";
import { sliceUnprocessedEvents } from "./hooks/eventCursor.js";
import { useSystemNotices } from "./hooks/useSystemNotices.js";
import type {
  ProtocolEvent,
  SessionSummaryItem,
  TokenUsage,
} from "./protocol/types.js";
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

function isSessionSummaryItem(value: unknown): value is SessionSummaryItem {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const record = value as Record<string, unknown>;
  if (typeof record["thread_id"] !== "string") {
    return false;
  }
  if (
    record["status"] !== "closed" &&
    record["status"] !== "incomplete"
  ) {
    return false;
  }
  if (typeof record["turn_count"] !== "number") {
    return false;
  }
  if (typeof record["token_total"] !== "number") {
    return false;
  }
  if (typeof record["date"] !== "string") {
    return false;
  }

  const lastUserMessage = record["last_user_message"];
  return (
    lastUserMessage === null ||
    typeof lastUserMessage === "string"
  );
}

export function toSessionSummaryItems(
  sessions: readonly unknown[],
): SessionSummaryItem[] {
  return sessions.filter(isSessionSummaryItem);
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

export function summarizeCompactionForTurns(
  turns: readonly TurnState[],
): {
  detail: TurnState["compaction"]["detail"];
  status: TurnState["compaction"]["status"];
} {
  const latestTurn = turns[turns.length - 1];
  if (latestTurn === undefined) {
    return {
      detail: null,
      status: "idle",
    };
  }

  if (latestTurn.status === "active" && latestTurn.compaction.status === "pending") {
    return {
      detail: null,
      status: "pending",
    };
  }

  return {
    detail: latestTurn.compaction.detail,
    status: latestTurn.compaction.status,
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
  const [sessionPickerSessions, setSessionPickerSessions] = useState<
    SessionSummaryItem[] | null
  >(null);
  const {
    turns,
    threadId,
    hasPendingUserInput,
    pendingUserInputWarning,
    queueUserInput,
  } = useTurns(events);
  const { currentRequest, decisionLog, queueLength, respond } = useApprovalQueue(events, writer);
  const systemNotices = useSystemNotices(events);
  const lastProcessedEventRef = useRef<ProtocolEvent | null>(null);

  useEffect(() => {
    if (events.length === 0) {
      setSessionPickerSessions(null);
      lastProcessedEventRef.current = null;
      return;
    }

    const unprocessedEvents = sliceUnprocessedEvents(
      events,
      lastProcessedEventRef.current,
    );
    for (const event of unprocessedEvents) {
      if (event.type !== "session.listed") {
        continue;
      }

      setSessionPickerSessions(
        toSessionSummaryItems(event.sessions as readonly unknown[]),
      );
    }
    lastProcessedEventRef.current = events[events.length - 1] ?? null;
  }, [events]);

  const isBusy = turns.some((turn) => turn.status === "active");
  const isSessionPickerOpen = sessionPickerSessions !== null;
  const inputDisabled =
    isInputDisabled(turns, queueLength, hasPendingUserInput) ||
    isSessionPickerOpen;
  const usageSummary = summarizeUsageForTurns(turns);
  const compactionSummary = summarizeCompactionForTurns(turns);

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

  const handleSessionSelect = useCallback((threadIdToResume: string): void => {
    writer.sendSessionResume(threadIdToResume);
    setSessionPickerSessions(null);
  }, [writer]);

  const handleSessionDismiss = useCallback((): void => {
    setSessionPickerSessions(null);
  }, []);

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
      {sessionPickerSessions !== null ? (
        <SessionPickerModal
          onDismiss={handleSessionDismiss}
          onSelect={handleSessionSelect}
          sessions={sessionPickerSessions}
        />
      ) : null}
      {systemNotices.map((notice) => (
        <Text dimColor key={notice.id}>
          {notice.text}
        </Text>
      ))}
      <InputArea
        disabled={inputDisabled}
        hasActiveTurn={isBusy}
        onExit={onExitRequested}
        onInterrupt={handleInterrupt}
        onSubmit={handleSubmit}
      />
      <StatusBar
        cumulativeUsage={usageSummary.cumulativeUsage}
        compactionDetail={compactionSummary.detail}
        compactionStatus={compactionSummary.status}
        isBusy={isBusy}
        latestUsage={usageSummary.latestUsage}
        threadId={threadId}
        turnCount={turns.length}
      />
    </Box>
  );
}
