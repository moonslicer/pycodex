import { useEffect, useState } from "react";
import { Box, Text, useInput } from "ink";

type InputAreaProps = {
  disabled: boolean;
  onInterrupt: () => void;
  onSubmit: (text: string) => void;
};

export function InputArea({
  disabled,
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
      onInterrupt();
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

    setValue((current) => `${current}${input}`);
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
