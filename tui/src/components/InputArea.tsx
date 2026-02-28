import { useEffect, useState } from "react";
import { Box, Text, useInput } from "ink";

type InputAreaProps = {
  disabled: boolean;
  onExit: () => void;
  onInterrupt: () => void;
  onSubmit: (text: string) => void;
};

const BRACKETED_PASTE_START = "\u001b[200~";
const BRACKETED_PASTE_END = "\u001b[201~";

export function handleCtrlC(disabled: boolean, callbacks: {
  onExit: () => void;
  onInterrupt: () => void;
}): void {
  if (disabled) {
    callbacks.onInterrupt();
  }
  callbacks.onExit();
}

export function sanitizeInputChunk(input: string): string {
  const withoutPasteMarkers = input
    .replaceAll(BRACKETED_PASTE_START, "")
    .replaceAll(BRACKETED_PASTE_END, "")
    .replace(/[\r\n]+/g, "");

  let sanitized = "";
  for (const char of withoutPasteMarkers) {
    const codepoint = char.codePointAt(0);
    if (codepoint === undefined) {
      continue;
    }
    if (codepoint <= 0x1f || codepoint === 0x7f) {
      continue;
    }
    sanitized += char;
  }

  return sanitized;
}

export function InputArea({
  disabled,
  onExit,
  onInterrupt,
  onSubmit,
}: InputAreaProps) {
  const [value, setValue] = useState("");

  useEffect(() => {
    if (disabled) {
      setValue("");
    }
  }, [disabled]);

  useInput((input, key) => {
    if (key.ctrl && input.toLowerCase() === "c") {
      handleCtrlC(disabled, { onExit, onInterrupt });
      return;
    }

    if (disabled) {
      return;
    }

    if (key.return) {
      const text = value.trim();
      if (text.length === 0) {
        return;
      }

      onSubmit(text);
      setValue("");
      return;
    }

    if (key.backspace || key.delete) {
      setValue((current) => current.slice(0, -1));
      return;
    }

    if (key.ctrl || key.meta || input.length === 0) {
      return;
    }

    const sanitizedChunk = sanitizeInputChunk(input);
    if (sanitizedChunk.length === 0) {
      return;
    }

    setValue((current) => `${current}${sanitizedChunk}`);
  });

  return (
    <Box borderStyle="single" paddingX={1}>
      {disabled ? (
        <Text color="yellow">Input disabled while turn is active</Text>
      ) : (
        <Text>{`> ${value}`}</Text>
      )}
    </Box>
  );
}
