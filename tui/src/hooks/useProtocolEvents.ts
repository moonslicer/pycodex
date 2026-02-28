import { useEffect, useState } from "react";

import type { ProtocolReader } from "../protocol/reader.js";
import type { ProtocolEvent } from "../protocol/types.js";

type ProtocolEventState = {
  events: ProtocolEvent[];
};

// Keep the last N events in memory. Consumers process from a last-event anchor
// so rolling-window truncation does not permanently stall event handling.
const MAX_EVENTS = 1000;

export function appendProtocolEvent(
  events: readonly ProtocolEvent[],
  event: ProtocolEvent,
): ProtocolEvent[] {
  const next = [...events, event];
  return next.length > MAX_EVENTS ? next.slice(-MAX_EVENTS) : next;
}

export function useProtocolEvents(reader: ProtocolReader): ProtocolEventState {
  const [events, setEvents] = useState<ProtocolEvent[]>([]);

  useEffect(() => {
    setEvents([]);

    const unsubscribe = reader.onEvent((event) => {
      setEvents((currentEvents) => appendProtocolEvent(currentEvents, event));
    });

    return () => {
      unsubscribe();
    };
  }, [reader]);

  return { events };
}
