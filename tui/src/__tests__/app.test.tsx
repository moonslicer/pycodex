/**
 * App-level integration smoke tests.
 *
 * Ink and its ESM-only dependency tree cannot be loaded via ts-jest's CJS
 * wrapper, so this file tests the app's state logic using the exported pure
 * reducer functions rather than rendering a full component tree.
 *
 * Component render tests (ChatView, InputArea, StatusBar) are deferred until a
 * compatible render harness (jest-environment-node + experimental VM modules)
 * is wired up.
 */
import type { ProtocolEvent } from "../protocol/types.js";
import { isInputDisabled } from "../app.js";
import {
  INITIAL_TURNS_STATE,
  reduceTurns,
  reduceTurnsSequence,
} from "../hooks/useTurns.js";
import { appendProtocolEvent } from "../hooks/useProtocolEvents.js";

// ---------------------------------------------------------------------------
// App-level smoke: full event sequence through protocol → state pipeline
// ---------------------------------------------------------------------------

describe("App state integration smoke", () => {
  test("thread.started → turn.started → turn.completed produces a completed turn", () => {
    const events: ProtocolEvent[] = [
      { type: "thread.started", thread_id: "thread_1" },
      { type: "turn.started", thread_id: "thread_1", turn_id: "turn_1" },
      {
        type: "turn.completed",
        thread_id: "thread_1",
        turn_id: "turn_1",
        final_text: "The answer is 42",
        usage: {
          turn: { input_tokens: 10, output_tokens: 5 },
          cumulative: { input_tokens: 10, output_tokens: 5 },
        },
      },
    ];

    const state = reduceTurnsSequence(INITIAL_TURNS_STATE, events);

    expect(state.threadId).toBe("thread_1");
    expect(state.turns).toHaveLength(1);
    expect(state.turns[0]?.status).toBe("completed");
    expect(state.turns[0]?.assistantLines).toEqual(["The answer is 42"]);
    expect(state.turns[0]?.usage).toEqual({
      turn: { input_tokens: 10, output_tokens: 5 },
      cumulative: { input_tokens: 10, output_tokens: 5 },
    });
  });

  test("isBusy is true during active turn, false after completion", () => {
    const afterStart = reduceTurnsSequence(INITIAL_TURNS_STATE, [
      { type: "thread.started", thread_id: "thread_1" },
      { type: "turn.started", thread_id: "thread_1", turn_id: "turn_1" },
    ]);

    const isBusyDuring = afterStart.turns.some((t) => t.status === "active");
    expect(isBusyDuring).toBe(true);

    const afterComplete = reduceTurns(afterStart, {
      type: "turn.completed",
      thread_id: "thread_1",
      turn_id: "turn_1",
      final_text: "done",
      usage: null,
    });

    const isBusyAfter = afterComplete.turns.some((t) => t.status === "active");
    expect(isBusyAfter).toBe(false);
  });

  test("turn.failed marks turn as failed and exposes error text", () => {
    const state = reduceTurnsSequence(INITIAL_TURNS_STATE, [
      { type: "thread.started", thread_id: "thread_1" },
      { type: "turn.started", thread_id: "thread_1", turn_id: "turn_1" },
      {
        type: "turn.failed",
        thread_id: "thread_1",
        turn_id: "turn_1",
        error: "interrupted",
      },
    ]);

    expect(state.turns[0]?.status).toBe("failed");
    expect(state.turns[0]?.error).toBe("interrupted");
    // input should be re-enabled (no active turns)
    expect(state.turns.some((t) => t.status === "active")).toBe(false);
  });

  test("multiple sequential turns accumulate correctly", () => {
    const events: ProtocolEvent[] = [
      { type: "thread.started", thread_id: "thread_1" },
      { type: "turn.started", thread_id: "thread_1", turn_id: "turn_1" },
      {
        type: "turn.completed",
        thread_id: "thread_1",
        turn_id: "turn_1",
        final_text: "First response",
        usage: null,
      },
      { type: "turn.started", thread_id: "thread_1", turn_id: "turn_2" },
      {
        type: "turn.completed",
        thread_id: "thread_1",
        turn_id: "turn_2",
        final_text: "Second response",
        usage: null,
      },
    ];

    const state = reduceTurnsSequence(INITIAL_TURNS_STATE, events);

    expect(state.turns).toHaveLength(2);
    expect(state.turns[0]?.assistantLines).toEqual(["First response"]);
    expect(state.turns[1]?.assistantLines).toEqual(["Second response"]);
  });

  test("appendProtocolEvent accumulates events and caps at MAX_EVENTS", () => {
    let events: readonly ProtocolEvent[] = [];

    const sampleEvent: ProtocolEvent = {
      type: "turn.started",
      thread_id: "t",
      turn_id: "r",
    };

    // Fill past the 1000-event cap
    for (let i = 0; i < 1005; i += 1) {
      events = appendProtocolEvent(events, sampleEvent);
    }

    // Should be capped at 1000
    expect(events.length).toBe(1000);
  });

  test("input is disabled while approval queue has pending requests", () => {
    const idleTurns = reduceTurnsSequence(INITIAL_TURNS_STATE, [
      { type: "thread.started", thread_id: "thread_1" },
    ]).turns;
    expect(isInputDisabled(idleTurns, 1, false)).toBe(true);
  });

  test("input is enabled only when no active turn and no approvals", () => {
    const completedTurns = reduceTurnsSequence(INITIAL_TURNS_STATE, [
      { type: "thread.started", thread_id: "thread_1" },
      { type: "turn.started", thread_id: "thread_1", turn_id: "turn_1" },
      {
        type: "turn.completed",
        thread_id: "thread_1",
        turn_id: "turn_1",
        final_text: "done",
        usage: null,
      },
    ]).turns;

    expect(isInputDisabled(completedTurns, 0, false)).toBe(false);
  });

  test("input is disabled while waiting for turn.started after submit", () => {
    const idleTurns = reduceTurnsSequence(INITIAL_TURNS_STATE, [
      { type: "thread.started", thread_id: "thread_1" },
    ]).turns;
    expect(isInputDisabled(idleTurns, 0, true)).toBe(true);
  });
});
