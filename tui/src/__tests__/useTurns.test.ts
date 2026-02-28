import type { ProtocolEvent } from "../protocol/types.js";
import {
  INITIAL_TURNS_STATE,
  reduceTurns,
  reduceTurnsSequence,
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
