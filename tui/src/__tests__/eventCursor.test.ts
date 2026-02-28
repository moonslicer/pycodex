import { sliceUnprocessedEvents } from "../hooks/eventCursor.js";
import type { ProtocolEvent } from "../protocol/types.js";

function makeTurnStarted(index: number): ProtocolEvent {
  return {
    type: "turn.started",
    thread_id: "thread_1",
    turn_id: `turn_${String(index)}`,
  };
}

describe("sliceUnprocessedEvents", () => {
  test("returns all events when no anchor exists", () => {
    const events = [makeTurnStarted(1), makeTurnStarted(2)];
    expect(sliceUnprocessedEvents(events, null)).toEqual(events);
  });

  test("returns only events after the anchor when anchor exists", () => {
    const events = [makeTurnStarted(1), makeTurnStarted(2), makeTurnStarted(3)];
    const anchor = events[1] ?? null;

    expect(sliceUnprocessedEvents(events, anchor)).toEqual([events[2]]);
  });

  test("returns full window when anchor rolled out of a capped buffer", () => {
    const allEvents = Array.from({ length: 1005 }, (_, index) =>
      makeTurnStarted(index + 1),
    );
    const cappedWindow = allEvents.slice(-1000);
    const evictedAnchor = allEvents[2] ?? null;

    expect(sliceUnprocessedEvents(cappedWindow, evictedAnchor)).toEqual(
      cappedWindow,
    );
  });

  test("returns empty when anchor is the newest event", () => {
    const events = [makeTurnStarted(1), makeTurnStarted(2)];
    const newest = events[events.length - 1] ?? null;

    expect(sliceUnprocessedEvents(events, newest)).toEqual([]);
  });

  test("returns empty for empty input", () => {
    expect(sliceUnprocessedEvents([], makeTurnStarted(1))).toEqual([]);
  });
});
