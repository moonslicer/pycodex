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

export const MAX_VISIBLE_SESSION_ROWS = 5;

export type VisibleSession = {
  session: SessionSummaryItem;
  originalIndex: number;
};

export function formatSessionPickerTitle(
  sessionsLength: number,
  selectedIndex: number,
): string {
  if (sessionsLength <= 0) {
    return "Resume Session";
  }
  const position = clampSessionSelection(selectedIndex, sessionsLength) + 1;
  return `Resume Session (${String(position)} of ${String(sessionsLength)})`;
}

export function getVisibleSessions(
  sessions: readonly SessionSummaryItem[],
  selectedIndex: number,
  maxVisible: number = MAX_VISIBLE_SESSION_ROWS,
): readonly VisibleSession[] {
  if (sessions.length === 0 || maxVisible <= 0) {
    return [];
  }

  const normalizedIndex = clampSessionSelection(selectedIndex, sessions.length);
  const windowSize = Math.min(sessions.length, maxVisible);
  const centeredStart = normalizedIndex - Math.floor(windowSize / 2);
  const maxStart = Math.max(0, sessions.length - windowSize);
  const start = Math.min(Math.max(centeredStart, 0), maxStart);
  const end = start + windowSize;

  const visible: VisibleSession[] = [];
  for (let index = start; index < end; index += 1) {
    const session = sessions[index];
    if (session !== undefined) {
      visible.push({ session, originalIndex: index });
    }
  }
  return visible;
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

export type FormattedSessionRow = {
  primary: string;
  secondary: string;
};

export function formatRelativeTime(updatedAt: string, nowMs: number = Date.now()): string {
  const updatedMs = Date.parse(updatedAt);
  if (!Number.isFinite(updatedMs)) {
    return "unknown time";
  }

  const deltaSeconds = Math.max(0, Math.floor((nowMs - updatedMs) / 1000));
  if (deltaSeconds < 60) {
    return "just now";
  }

  const minute = 60;
  const hour = 60 * minute;
  const day = 24 * hour;
  const week = 7 * day;
  const month = 30 * day;
  const year = 365 * day;

  if (deltaSeconds < hour) {
    return `${String(Math.floor(deltaSeconds / minute))}m ago`;
  }
  if (deltaSeconds < day) {
    return `${String(Math.floor(deltaSeconds / hour))}h ago`;
  }
  if (deltaSeconds < week) {
    return `${String(Math.floor(deltaSeconds / day))}d ago`;
  }
  if (deltaSeconds < month) {
    return `${String(Math.floor(deltaSeconds / week))}w ago`;
  }
  if (deltaSeconds < year) {
    return `${String(Math.floor(deltaSeconds / month))}mo ago`;
  }
  return `${String(Math.floor(deltaSeconds / year))}y ago`;
}

export function formatSizeBytes(sizeBytes: number): string {
  if (!Number.isFinite(sizeBytes) || sizeBytes < 0) {
    return "0B";
  }

  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = sizeBytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  if (unitIndex === 0) {
    return `${String(Math.round(value))}${units[unitIndex] ?? "B"}`;
  }

  const formatted = value.toFixed(1).replace(/\.0$/, "");
  return `${formatted}${units[unitIndex] ?? "B"}`;
}

export function formatSessionRow(
  session: SessionSummaryItem,
  nowMs: number = Date.now(),
): FormattedSessionRow {
  const preview = truncateForDisplay(
    session.last_user_message?.trim() || "No prompt yet",
    96,
  );
  const relativeTime = formatRelativeTime(session.updated_at, nowMs);
  const size = formatSizeBytes(session.size_bytes);
  return {
    primary: preview,
    secondary: `${relativeTime} · ${size}`,
  };
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

  const visibleSessions = getVisibleSessions(sessions, selectedIndex);
  const title = formatSessionPickerTitle(sessions.length, selectedIndex);
  const selectedPosition =
    sessions.length === 0
      ? 0
      : clampSessionSelection(selectedIndex, sessions.length) + 1;

  return (
    <Box borderStyle="round" flexDirection="column" marginBottom={1} paddingX={1}>
      <Text bold>{title}</Text>
      {sessions.length === 0 ? (
        <Text color="yellow">No sessions available.</Text>
      ) : (
        visibleSessions.map(({ session, originalIndex }) => {
          const selected = originalIndex === selectedIndex;
          const row = formatSessionRow(session);
          return (
            <Box flexDirection="column" key={session.thread_id}>
              <Text inverse={selected}>{row.primary}</Text>
              <Text inverse={selected}>{row.secondary}</Text>
            </Box>
          );
        })
      )}
      {sessions.length > 0 ? (
        <Text dimColor>{`[up/down ${String(selectedPosition)}/${String(sessions.length)}] [Enter] resume [Esc] cancel`}</Text>
      ) : (
        <Text dimColor>[Enter] resume  [Esc] cancel</Text>
      )}
    </Box>
  );
}
