import {
  INITIAL_LINE_BUFFER_STATE,
  reduceLineBuffer,
  type LineBufferAction,
  type LineBufferState,
} from "../hooks/useLineBuffer.js";

function applyActions(
  initialState: LineBufferState,
  actions: readonly LineBufferAction[],
): LineBufferState {
  let nextState = initialState;
  for (const action of actions) {
    nextState = reduceLineBuffer(nextState, action);
  }
  return nextState;
}

describe("reduceLineBuffer", () => {
  test("push commits newline-delimited text and retains trailing partial", () => {
    const next = reduceLineBuffer(INITIAL_LINE_BUFFER_STATE, {
      type: "push",
      delta: "hello\nwor",
    });

    expect(next.committed).toEqual(["hello"]);
    expect(next.partial).toBe("wor");
  });

  test("push preserves intentional blank committed lines", () => {
    const next = reduceLineBuffer(INITIAL_LINE_BUFFER_STATE, {
      type: "push",
      delta: "line one\n\nline three\n",
    });

    expect(next.committed).toEqual(["line one", "", "line three"]);
    expect(next.partial).toBe("");
  });

  test("flush appends non-empty partial and drops trailing empty partial", () => {
    const fromPartial = applyActions(INITIAL_LINE_BUFFER_STATE, [
      { type: "push", delta: "alpha\nbeta" },
      { type: "flush" },
    ]);
    expect(fromPartial.committed).toEqual(["alpha", "beta"]);
    expect(fromPartial.partial).toBe("");

    const fromTrailingNewline = applyActions(INITIAL_LINE_BUFFER_STATE, [
      { type: "push", delta: "alpha\n" },
      { type: "flush" },
    ]);
    expect(fromTrailingNewline.committed).toEqual(["alpha"]);
    expect(fromTrailingNewline.partial).toBe("");
  });

  test("reset clears committed lines and partial text", () => {
    const next = applyActions(INITIAL_LINE_BUFFER_STATE, [
      { type: "push", delta: "abc\ndef" },
      { type: "reset" },
    ]);

    expect(next).toEqual(INITIAL_LINE_BUFFER_STATE);
  });
});
