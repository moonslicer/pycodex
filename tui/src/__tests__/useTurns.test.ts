import type { ProtocolEvent } from "../protocol/types.js";
import {
  dequeuePendingUserInput,
  enqueuePendingUserInput,
  INITIAL_TURNS_STATE,
  reduceTurns,
  reduceTurnsSequence,
  turnsReducer,
  type TurnsViewState,
} from "../hooks/useTurns.js";

const ABORT_TEXT = "Aborted by user.";
const INTERRUPTED_ERROR = "interrupted";

describe("reduceTurns", () => {
  test("turn.started appends an active turn", () => {
    const next = reduceTurns(INITIAL_TURNS_STATE, {
      type: "turn.started",
      thread_id: "thread_1",
      turn_id: "turn_1",
    });

    expect(next.turns).toHaveLength(1);
    expect(next.turns[0]?.turn_id).toBe("turn_1");
    expect(next.turns[0]?.status).toBe("active");
  });

  test("turn.completed records final text and usage", () => {
    const started = reduceTurns(INITIAL_TURNS_STATE, {
      type: "turn.started",
      thread_id: "thread_1",
      turn_id: "turn_1",
    });

    const completed = reduceTurns(started, {
      type: "turn.completed",
      thread_id: "thread_1",
      turn_id: "turn_1",
      final_text: "line one\nline two",
      usage: {
        turn: { input_tokens: 5, output_tokens: 8 },
        cumulative: { input_tokens: 5, output_tokens: 8 },
      },
    });

    expect(completed.turns[0]?.status).toBe("completed");
    expect(completed.turns[0]?.assistantLines).toEqual(["line one", "line two"]);
    expect(completed.turns[0]?.usage).toEqual({
      turn: { input_tokens: 5, output_tokens: 8 },
      cumulative: { input_tokens: 5, output_tokens: 8 },
    });
  });

  test("item.updated commits newline segments and keeps trailing partial", () => {
    const next = reduceTurnsSequence(INITIAL_TURNS_STATE, [
      {
        type: "turn.started",
        thread_id: "thread_1",
        turn_id: "turn_1",
      },
      {
        type: "item.updated",
        thread_id: "thread_1",
        turn_id: "turn_1",
        item_id: "item_1",
        delta: "line one\nline",
      },
      {
        type: "item.updated",
        thread_id: "thread_1",
        turn_id: "turn_1",
        item_id: "item_1",
        delta: " two",
      },
    ]);

    expect(next.turns[0]?.assistantLines).toEqual(["line one"]);
    expect(next.turns[0]?.partialLine).toBe("line two");
  });

  test("turn.completed with empty final text flushes buffered partial", () => {
    const next = reduceTurnsSequence(INITIAL_TURNS_STATE, [
      {
        type: "turn.started",
        thread_id: "thread_1",
        turn_id: "turn_1",
      },
      {
        type: "item.updated",
        thread_id: "thread_1",
        turn_id: "turn_1",
        item_id: "item_1",
        delta: "line one\n\nline",
      },
      {
        type: "turn.completed",
        thread_id: "thread_1",
        turn_id: "turn_1",
        final_text: "",
        usage: null,
      },
    ]);

    expect(next.turns[0]?.assistantLines).toEqual(["line one", "", "line"]);
    expect(next.turns[0]?.partialLine).toBe("");
    expect(next.turns[0]?.status).toBe("completed");
  });

  test("turn.completed final text drops trailing empty partial line", () => {
    const next = reduceTurnsSequence(INITIAL_TURNS_STATE, [
      {
        type: "turn.started",
        thread_id: "thread_1",
        turn_id: "turn_1",
      },
      {
        type: "turn.completed",
        thread_id: "thread_1",
        turn_id: "turn_1",
        final_text: "line one\n",
        usage: null,
      },
    ]);

    expect(next.turns[0]?.assistantLines).toEqual(["line one"]);
  });

  test.each([
    {
      name: "abort completion maps to completed turn",
      terminalEvent: {
        type: "turn.completed" as const,
        thread_id: "thread_1",
        turn_id: "turn_1",
        final_text: ABORT_TEXT,
        usage: null,
      },
      expectedStatus: "completed" as const,
      expectedError: null,
      expectedAssistantLines: [ABORT_TEXT],
    },
    {
      name: "interrupt maps to failed turn",
      terminalEvent: {
        type: "turn.failed" as const,
        thread_id: "thread_1",
        turn_id: "turn_1",
        error: INTERRUPTED_ERROR,
      },
      expectedStatus: "failed" as const,
      expectedError: INTERRUPTED_ERROR,
      expectedAssistantLines: [],
    },
  ])(
    "$name",
    ({ terminalEvent, expectedStatus, expectedError, expectedAssistantLines }) => {
      const next = reduceTurnsSequence(INITIAL_TURNS_STATE, [
        {
          type: "turn.started",
          thread_id: "thread_1",
          turn_id: "turn_1",
        },
        terminalEvent,
      ]);

      expect(next.turns[0]?.status).toBe(expectedStatus);
      expect(next.turns[0]?.error).toBe(expectedError);
      expect(next.turns[0]?.assistantLines).toEqual(expectedAssistantLines);
    },
  );

  test("item.started tool_call is tracked with name and arguments", () => {
    const next = reduceTurnsSequence(INITIAL_TURNS_STATE, [
      {
        type: "turn.started",
        thread_id: "thread_1",
        turn_id: "turn_1",
      },
      {
        type: "item.started",
        thread_id: "thread_1",
        turn_id: "turn_1",
        item_id: "item_1",
        item_kind: "tool_call",
        name: "shell",
        arguments: "{\"command\":\"ls -lrt\"}",
      },
    ]);

    expect(next.turns[0]?.toolCalls["item_1"]).toEqual({
      item_id: "item_1",
      name: "shell",
      arguments: "{\"command\":\"ls -lrt\"}",
      status: "pending",
      content: null,
    });
  });

  test("item.completed tool_result marks the tool call done", () => {
    const next = reduceTurnsSequence(INITIAL_TURNS_STATE, [
      {
        type: "turn.started",
        thread_id: "thread_1",
        turn_id: "turn_1",
      },
      {
        type: "item.started",
        thread_id: "thread_1",
        turn_id: "turn_1",
        item_id: "item_1",
        item_kind: "tool_call",
        name: "shell",
        arguments: null,
      },
      {
        type: "item.completed",
        thread_id: "thread_1",
        turn_id: "turn_1",
        item_id: "item_1",
        item_kind: "tool_result",
        content: "stdout:\nfile.txt",
      },
    ]);

    expect(next.turns[0]?.toolCalls["item_1"]).toEqual({
      item_id: "item_1",
      name: "shell",
      arguments: null,
      status: "done",
      content: "stdout:\nfile.txt",
    });
  });

  test("assistant message items do not create tool call entries", () => {
    const next = reduceTurnsSequence(INITIAL_TURNS_STATE, [
      {
        type: "turn.started",
        thread_id: "thread_1",
        turn_id: "turn_1",
      },
      {
        type: "item.started",
        thread_id: "thread_1",
        turn_id: "turn_1",
        item_id: "item_assistant",
        item_kind: "assistant_message",
        name: null,
        arguments: null,
      },
    ]);

    expect(Object.keys(next.turns[0]?.toolCalls ?? {})).toHaveLength(0);
  });

  test("item.updated.batch applies multiple deltas in order", () => {
    const started = reduceTurns(INITIAL_TURNS_STATE, {
      type: "turn.started",
      thread_id: "thread_1",
      turn_id: "turn_1",
    });

    const result = turnsReducer(started, {
      type: "item.updated.batch",
      updates: [
        { turn_id: "turn_1", delta: "hello\n" },
        { turn_id: "turn_1", delta: "world" },
      ],
    });

    expect(result.turns[0]?.assistantLines).toEqual(["hello"]);
    expect(result.turns[0]?.partialLine).toBe("world");
  });

  test("item.updated.batch with empty updates returns same state reference", () => {
    const state: TurnsViewState = { threadId: "thread_1", turns: [] };
    const result = turnsReducer(state, { type: "item.updated.batch", updates: [] });
    expect(result).toBe(state);
  });

  test("unknown event does not mutate state", () => {
    const state: TurnsViewState = {
      threadId: "thread_1",
      turns: [],
    };

    const result = reduceTurns(
      state,
      {
        type: "unknown.event",
      } as unknown as ProtocolEvent,
    );

    expect(result).toBe(state);
  });

  test("event burst keeps order for started then completed", () => {
    const next = reduceTurnsSequence(INITIAL_TURNS_STATE, [
      {
        type: "turn.started",
        thread_id: "thread_1",
        turn_id: "turn_1",
      },
      {
        type: "turn.completed",
        thread_id: "thread_1",
        turn_id: "turn_1",
        final_text: "done",
        usage: null,
      },
    ]);

    expect(next.turns).toHaveLength(1);
    expect(next.turns[0]?.status).toBe("completed");
    expect(next.turns[0]?.assistantLines).toEqual(["done"]);
  });

  test("enqueuePendingUserInput appends user text in order", () => {
    const queued = enqueuePendingUserInput(null, "first");
    expect(queued).toEqual({
      accepted: true,
      nextSlot: "first",
    });
  });

  test("enqueuePendingUserInput rejects second pending input", () => {
    const queued = enqueuePendingUserInput("first", "second");
    expect(queued).toEqual({
      accepted: false,
      nextSlot: "first",
    });
  });

  test("dequeuePendingUserInput returns pending text and clears slot", () => {
    const dequeued = dequeuePendingUserInput("first");
    expect(dequeued).toEqual({
      nextSlot: null,
      text: "first",
    });
  });

  test("dequeuePendingUserInput returns null text for empty slot", () => {
    const dequeued = dequeuePendingUserInput(null);
    expect(dequeued).toEqual({
      nextSlot: null,
      text: null,
    });
  });
});
