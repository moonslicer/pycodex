import {
  handleCtrlC,
  handleCtrlX,
  isSubmitInput,
  sanitizeInputChunk,
} from "../components/InputArea.js";

describe("sanitizeInputChunk", () => {
  test("keeps ordinary printable text unchanged", () => {
    expect(sanitizeInputChunk("hello, world")).toBe("hello, world");
  });

  test("strips bracketed paste markers", () => {
    const raw = '\u001b[200~Write 12 short lines about HTTP.\u001b[201~';
    expect(sanitizeInputChunk(raw)).toBe("Write 12 short lines about HTTP.");
  });

  test("removes newlines and control characters from pasted chunks", () => {
    const raw = "line 1\r\nline 2\u0007";
    expect(sanitizeInputChunk(raw)).toBe("line 1line 2");
  });
});

describe("handleCtrlC", () => {
  test("sends interrupt while turn is active", () => {
    const onInterrupt = jest.fn();

    handleCtrlC(true, { onInterrupt });

    expect(onInterrupt).toHaveBeenCalledTimes(1);
  });

  test("does nothing when no turn is active", () => {
    const onInterrupt = jest.fn();

    handleCtrlC(false, { onInterrupt });

    expect(onInterrupt).not.toHaveBeenCalled();
  });
});

describe("handleCtrlX", () => {
  test("exits directly", () => {
    const onExit = jest.fn();

    handleCtrlX({ onExit });

    expect(onExit).toHaveBeenCalledTimes(1);
  });
});

describe("isSubmitInput", () => {
  test("submits when key return is set", () => {
    expect(isSubmitInput("", true)).toBe(true);
  });

  test("submits on bare newline fallback when key metadata is missing", () => {
    expect(isSubmitInput("\n", false)).toBe(true);
    expect(isSubmitInput("\r", false)).toBe(true);
    expect(isSubmitInput("\r\n", false)).toBe(true);
  });

  test("does not submit for pasted text containing newlines", () => {
    expect(isSubmitInput("line 1\nline 2", false)).toBe(false);
    expect(isSubmitInput("\u001b[200~line 1\nline 2\u001b[201~", false)).toBe(
      false,
    );
  });
});
