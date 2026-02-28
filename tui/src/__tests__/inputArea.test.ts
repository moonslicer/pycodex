import { handleCtrlC, sanitizeInputChunk } from "../components/InputArea.js";

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
  test("sends interrupt then exits while turn is active", () => {
    const onInterrupt = jest.fn();
    const onExit = jest.fn();

    handleCtrlC(true, { onExit, onInterrupt });

    expect(onInterrupt).toHaveBeenCalledTimes(1);
    expect(onExit).toHaveBeenCalledTimes(1);
    expect(onInterrupt.mock.invocationCallOrder[0]).toBeLessThan(
      onExit.mock.invocationCallOrder[0] ?? 0,
    );
  });

  test("exits directly when no turn is active", () => {
    const onInterrupt = jest.fn();
    const onExit = jest.fn();

    handleCtrlC(false, { onExit, onInterrupt });

    expect(onInterrupt).not.toHaveBeenCalled();
    expect(onExit).toHaveBeenCalledTimes(1);
  });
});
