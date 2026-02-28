import { handleCtrlC, handleCtrlX, sanitizeInputChunk } from "../components/InputArea.js";

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
