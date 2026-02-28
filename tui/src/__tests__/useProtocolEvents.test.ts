import { appendProtocolEvent } from "../hooks/useProtocolEvents.js";
import type { ProtocolEvent } from "../protocol/types.js";

describe("appendProtocolEvent", () => {
  test("preserves prior events when appending", () => {
    const existing: ProtocolEvent[] = [
      {
        type: "turn.started",
        thread_id: "thread_1",
        turn_id: "turn_1",
      },
    ];

    const appended = appendProtocolEvent(existing, {
      type: "turn.completed",
      thread_id: "thread_1",
      turn_id: "turn_1",
      final_text: "done",
      usage: null,
    });

    expect(appended).toHaveLength(2);
    expect(appended[0]).toEqual(existing[0]);
    expect(appended[1]).toEqual({
      type: "turn.completed",
      thread_id: "thread_1",
      turn_id: "turn_1",
      final_text: "done",
      usage: null,
    });
    expect(existing).toHaveLength(1);
  });
});
