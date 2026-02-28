import { useEffect, useState } from "react";

import type { ProtocolReader } from "../protocol/reader.js";
import type { ProtocolEvent } from "../protocol/types.js";

type ProtocolEventState = {
  events: ProtocolEvent[];
};

export function appendProtocolEvent(
  events: readonly ProtocolEvent[],
  event: ProtocolEvent,
): ProtocolEvent[] {
  return [...events, event];
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
