import { useEffect, useState } from "react";
import { Box, Text, useInput } from "ink";

import type { SessionSummaryItem } from "../protocol/types.js";

type SessionPickerModalProps = {
  sessions: SessionSummaryItem[];
  onSelect: (threadId: string) => void;
  onDismiss: () => void;
};

type PickerKey = {
  downArrow: boolean;
  upArrow: boolean;
  return: boolean;
  escape?: boolean;
};

export function clampSessionSelection(
  selectedIndex: number,
  sessionsLength: number,
): number {
  if (sessionsLength <= 0) {
    return 0;
  }

  return Math.min(Math.max(selectedIndex, 0), sessionsLength - 1);
}

export function truncateForDisplay(value: string, maxLength: number): string {
  if (maxLength <= 0) {
    return "";
  }
  if (value.length <= maxLength) {
    return value;
  }
  if (maxLength <= 3) {
    return ".".repeat(maxLength);
  }

  return `${value.slice(0, maxLength - 3)}...`;
}

export function formatSessionRow(session: SessionSummaryItem): string {
  const threadId = truncateForDisplay(session.thread_id, 12);
  const status = session.status;
  const lastMessage = truncateForDisplay(session.last_user_message ?? "", 48);

  return `${session.date}  ${threadId}  turns:${String(session.turn_count)}  tokens:${String(session.token_total)}  ${status}  ${lastMessage}`;
}

export function handleSessionPickerKey(
  input: string,
  key: PickerKey,
  selectedIndex: number,
  sessions: readonly SessionSummaryItem[],
): {
  action: "none" | "up" | "down" | "select" | "dismiss";
  nextIndex: number;
  selectedThreadId: string | null;
} {
  if (key.upArrow || input === "k") {
    return {
      action: "up",
      nextIndex: clampSessionSelection(selectedIndex - 1, sessions.length),
      selectedThreadId: null,
    };
  }
  if (key.downArrow || input === "j") {
    return {
      action: "down",
      nextIndex: clampSessionSelection(selectedIndex + 1, sessions.length),
      selectedThreadId: null,
    };
  }
  if (key.return) {
    const selected = sessions[selectedIndex];
    return {
      action: selected === undefined ? "none" : "select",
      nextIndex: selectedIndex,
      selectedThreadId: selected?.thread_id ?? null,
    };
  }
  if (key.escape ?? false) {
    return {
      action: "dismiss",
      nextIndex: selectedIndex,
      selectedThreadId: null,
    };
  }

  return {
    action: "none",
    nextIndex: selectedIndex,
    selectedThreadId: null,
  };
}

export function SessionPickerModal({
  sessions,
  onSelect,
  onDismiss,
}: SessionPickerModalProps) {
  const [selectedIndex, setSelectedIndex] = useState(0);

  useEffect(() => {
    setSelectedIndex((currentIndex) =>
      clampSessionSelection(currentIndex, sessions.length),
    );
  }, [sessions.length]);

  useInput((input, key) => {
    const result = handleSessionPickerKey(input, key, selectedIndex, sessions);

    if (result.nextIndex !== selectedIndex) {
      setSelectedIndex(result.nextIndex);
    }

    if (result.action === "select" && result.selectedThreadId !== null) {
      onSelect(result.selectedThreadId);
    }
    if (result.action === "dismiss") {
      onDismiss();
    }
  });

  return (
    <Box borderStyle="round" flexDirection="column" marginBottom={1} paddingX={1}>
      <Text bold>Resume Session</Text>
      {sessions.length === 0 ? (
        <Text color="yellow">No sessions available.</Text>
      ) : (
        sessions.map((session, index) => (
          <Text inverse={index === selectedIndex} key={session.thread_id}>
            {formatSessionRow(session)}
          </Text>
        ))
      )}
      <Text dimColor>[Enter] resume  [Esc] cancel</Text>
    </Box>
  );
}
