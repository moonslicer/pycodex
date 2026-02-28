import { useEffect, useState } from "react";
import { Text } from "ink";

const FRAMES = ["-", "\\", "|", "/"] as const;
const FRAME_INTERVAL_MS = 120;

type SpinnerProps = {
  label: string;
};

export function Spinner({ label }: SpinnerProps) {
  const [frameIndex, setFrameIndex] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setFrameIndex((current) => (current + 1) % FRAMES.length);
    }, FRAME_INTERVAL_MS);

    return () => {
      clearInterval(timer);
    };
  }, []);

  const frame = FRAMES[frameIndex] ?? "-";
  return <Text dimColor>{`${label} ${frame}`}</Text>;
}
