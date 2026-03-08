import { Box, Text } from "ink";

import type {
  ContextCompactedEvent,
  SessionStatusEvent,
  TokenUsage,
} from "../protocol/types.js";

type StatusBarProps = {
  cumulativeUsage: TokenUsage | null;
  compactionDetail: ContextCompactedEvent | null;
  compactionStatus: "pending" | "triggered" | "idle";
  isBusy: boolean;
  latestUsage: TokenUsage | null;
  pressureWarningActive: boolean;
  sessionStatus: SessionStatusEvent | null;
  threadId: string | null;
  turnCount: number;
};

function formatUsageValue(usage: TokenUsage): string {
  return `${String(usage.input_tokens)}/${String(usage.output_tokens)}`;
}

export function formatUsageSummary(
  latestUsage: TokenUsage | null,
  cumulativeUsage: TokenUsage | null,
): string {
  if (latestUsage !== null && cumulativeUsage !== null) {
    return `usage latest(in/out): ${formatUsageValue(latestUsage)} | total(in/out): ${formatUsageValue(cumulativeUsage)}`;
  }
  if (latestUsage !== null) {
    return `usage latest(in/out): ${formatUsageValue(latestUsage)}`;
  }
  if (cumulativeUsage !== null) {
    return `usage total(in/out): ${formatUsageValue(cumulativeUsage)}`;
  }
  return "usage: n/a";
}

function clampRatio(value: number): number {
  if (value < 0) {
    return 0;
  }
  if (value > 1) {
    return 1;
  }
  return value;
}

function formatContextWindow(value: number): string {
  if (value >= 1000) {
    return `${String(Math.round(value / 1000))}k`;
  }
  return String(value);
}

function renderAsciiBar(ratio: number): string {
  const slots = 10;
  const clamped = clampRatio(ratio);
  const filled = Math.round(clamped * slots);
  const empty = slots - filled;
  return `[${"#".repeat(filled)}${"-".repeat(empty)}]`;
}

export function formatContextMeter(status: SessionStatusEvent | null): string | null {
  if (status === null || status.context_window_tokens <= 0) {
    return null;
  }

  const fillRatio = status.estimated_prompt_tokens / status.context_window_tokens;
  return `context: ${renderAsciiBar(fillRatio)} ${toPercentage(clampRatio(fillRatio))} (${formatContextWindow(status.context_window_tokens)})`;
}

export function formatCompactionCount(count: number): string | null {
  if (count <= 0) {
    return null;
  }
  return `compacted: ${String(count)}x`;
}

function toPercentage(value: number): string {
  return `${(Math.round(value * 1000) / 10).toFixed(1)}%`;
}

export function formatCompactionSummary(
  status: "pending" | "triggered" | "idle",
  detail: ContextCompactedEvent | null,
): string {
  if (status === "pending") {
    return "compaction: pending";
  }
  if (detail !== null) {
    const contextFillRatio =
      detail.context_window_tokens <= 0
        ? 0
        : detail.estimated_prompt_tokens / detail.context_window_tokens;
    const thresholdFillRatio = 1 - detail.threshold_ratio;
    const replaced = String(detail.replaced_items);
    return `compaction: ${status} (replaced ${replaced}; context ${toPercentage(contextFillRatio)} / threshold ${toPercentage(thresholdFillRatio)})`;
  }
  return `compaction: ${status}`;
}

export function StatusBar({
  cumulativeUsage,
  compactionDetail,
  compactionStatus,
  isBusy,
  latestUsage,
  pressureWarningActive,
  sessionStatus,
  threadId,
  turnCount,
}: StatusBarProps) {
  const statusLabel = isBusy ? "busy" : "idle";
  const threadLabel = threadId ?? "pending";
  const turnCountLabel = String(turnCount);
  const usageLabel = formatUsageSummary(latestUsage, cumulativeUsage);
  const compactionLabel = formatCompactionSummary(compactionStatus, compactionDetail);
  const contextLabel = formatContextMeter(sessionStatus);
  const compactionCountLabel = formatCompactionCount(sessionStatus?.compaction_count ?? 0);
  const compactionCountSuffix =
    compactionCountLabel === null ? "" : ` | ${compactionCountLabel}`;

  if (contextLabel === null) {
    return <Text dimColor>{`thread: ${threadLabel} | turns: ${turnCountLabel} | status: ${statusLabel} | ${usageLabel} | ${compactionLabel}${compactionCountSuffix}`}</Text>;
  }

  return (
    <Box>
      <Text dimColor>{`thread: ${threadLabel} | turns: ${turnCountLabel} | status: ${statusLabel} | `}</Text>
      {pressureWarningActive ? (
        <Text color="yellow">{contextLabel}</Text>
      ) : (
        <Text dimColor>{contextLabel}</Text>
      )}
      <Text dimColor>{` | ${usageLabel} | ${compactionLabel}${compactionCountSuffix}`}</Text>
    </Box>
  );
}
