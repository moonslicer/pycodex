import { useEffect, useState } from "react";
import { Box, Text, useInput } from "ink";

type InputAreaProps = {
  disabled: boolean;
  hasActiveTurn: boolean;
  onExit: () => void;
  onInterrupt: () => void;
  onSubmit: (text: string) => void;
};

const BRACKETED_PASTE_START = "\u001b[200~";
const BRACKETED_PASTE_END = "\u001b[201~";

export function handleCtrlC(hasActiveTurn: boolean, callbacks: {
  onInterrupt: () => void;
}): void {
  if (hasActiveTurn) {
    callbacks.onInterrupt();
  }
}

export function handleCtrlX(callbacks: {
  onExit: () => void;
}): void {
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

export function isSubmitInput(input: string, keyReturn: boolean): boolean {
  if (keyReturn) {
    return true;
  }

  const withoutPasteMarkers = input
    .replaceAll(BRACKETED_PASTE_START, "")
    .replaceAll(BRACKETED_PASTE_END, "");
  if (!/[\r\n]/.test(withoutPasteMarkers)) {
    return false;
  }
  return withoutPasteMarkers.replace(/[\r\n]/g, "").length === 0;
}

export function InputArea({
  disabled,
  hasActiveTurn,
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
      handleCtrlC(hasActiveTurn, { onInterrupt });
      return;
    }

    if (key.ctrl && input.toLowerCase() === "x") {
      handleCtrlX({ onExit });
      return;
    }

    if (disabled) {
      return;
    }

    if (isSubmitInput(input, key.return)) {
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
        <Text color="yellow">
          Input disabled while a turn is active or approval is pending
        </Text>
      ) : (
        <Text>{`> ${value}`}</Text>
      )}
    </Box>
  );
}
