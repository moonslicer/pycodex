import { Text } from "ink";

type StatusBarProps = {
  isBusy: boolean;
  threadId: string | null;
  turnCount: number;
};

export function StatusBar({
  isBusy,
  threadId,
  turnCount,
}: StatusBarProps) {
  const statusLabel = isBusy ? "busy" : "idle";
  const threadLabel = threadId ?? "pending";
  const turnCountLabel = String(turnCount);

  return (
    <Text dimColor>{`thread: ${threadLabel} | turns: ${turnCountLabel} | status: ${statusLabel}`}</Text>
  );
}
