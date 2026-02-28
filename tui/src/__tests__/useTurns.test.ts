import type { ProtocolEvent } from "../protocol/types.js";
import {
  INITIAL_TURNS_STATE,
  reduceTurns,
  reduceTurnsSequence,
  turnsReducer,
  type TurnsViewState,
} from "../hooks/useTurns.js";

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
        input_tokens: 5,
        output_tokens: 8,
      },
    });

    expect(completed.turns[0]?.status).toBe("completed");
    expect(completed.turns[0]?.assistantLines).toEqual(["line one", "line two"]);
    expect(completed.turns[0]?.usage).toEqual({
      input_tokens: 5,
      output_tokens: 8,
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

  test("turn.failed stores error and marks failed state", () => {
    const started = reduceTurns(INITIAL_TURNS_STATE, {
      type: "turn.started",
      thread_id: "thread_1",
      turn_id: "turn_1",
    });

    const failed = reduceTurns(started, {
      type: "turn.failed",
      thread_id: "thread_1",
      turn_id: "turn_1",
      error: "interrupted",
    });

    expect(failed.turns[0]?.status).toBe("failed");
    expect(failed.turns[0]?.error).toBe("interrupted");
  });

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
});
