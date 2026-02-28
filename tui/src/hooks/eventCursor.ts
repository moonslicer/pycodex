import type { ProtocolEvent } from "../protocol/types.js";

/**
 * Returns only events that come after the last processed event object.
 *
 * The protocol event list is a capped rolling window. If the last processed
 * event has rolled out of the window, this returns the full current window so
 * consumers continue progressing instead of stalling.
 */
export function sliceUnprocessedEvents(
  events: readonly ProtocolEvent[],
  lastProcessedEvent: ProtocolEvent | null,
): readonly ProtocolEvent[] {
  if (events.length === 0 || lastProcessedEvent === null) {
    return events;
  }

  const anchorIndex = events.lastIndexOf(lastProcessedEvent);
  if (anchorIndex === -1) {
    return events;
  }

  return events.slice(anchorIndex + 1);
}
