import { useEffect, useRef, useState } from "react";

import type { ProtocolEvent } from "../protocol/types.js";
import { sliceUnprocessedEvents } from "./eventCursor.js";

export type SystemNotice = {
  id: string;
  text: string;
};

type NoticeUpdateResult = {
  notices: SystemNotice[];
  lastProcessedEvent: ProtocolEvent | null;
  nextNoticeIndex: number;
};

export function toSystemNoticeText(event: ProtocolEvent): string | null {
  switch (event.type) {
    case "session.status":
      return `Session ${event.thread_id}: turns=${String(event.turn_count)} tokens(in/out)=${String(event.input_tokens)}/${String(event.output_tokens)} context_window=${String(event.context_window_tokens)} compacted=${String(event.compaction_count)}`;
    case "slash.unknown":
      return `Unknown command: /${event.command}`;
    case "slash.blocked":
      return `Blocked: /${event.command} cannot run during an active turn.`;
    case "session.error":
      return `Session ${event.operation} failed: ${event.message}`;
    default:
      return null;
  }
}

export function updateSystemNotices(
  currentNotices: SystemNotice[],
  events: readonly ProtocolEvent[],
  lastProcessedEvent: ProtocolEvent | null,
  nextNoticeIndex: number,
): NoticeUpdateResult {
  if (events.length === 0) {
    return {
      notices: [],
      lastProcessedEvent: null,
      nextNoticeIndex: 1,
    };
  }

  const unprocessedEvents = sliceUnprocessedEvents(events, lastProcessedEvent);
  if (unprocessedEvents.length === 0) {
    return {
      notices: currentNotices,
      lastProcessedEvent,
      nextNoticeIndex,
    };
  }

  const nextNotices = [...currentNotices];
  let nextIndex = nextNoticeIndex;
  for (const event of unprocessedEvents) {
    const text = toSystemNoticeText(event);
    if (text === null) {
      continue;
    }

    nextNotices.push({
      id: `notice_${String(nextIndex)}`,
      text,
    });
    nextIndex += 1;
  }

  return {
    notices: nextNotices,
    lastProcessedEvent: events[events.length - 1] ?? lastProcessedEvent,
    nextNoticeIndex: nextIndex,
  };
}

export function useSystemNotices(
  events: readonly ProtocolEvent[],
): readonly SystemNotice[] {
  const [notices, setNotices] = useState<SystemNotice[]>([]);
  const lastProcessedEventRef = useRef<ProtocolEvent | null>(null);
  const nextNoticeIndexRef = useRef(1);

  useEffect(() => {
    setNotices((currentNotices) => {
      const next = updateSystemNotices(
        currentNotices,
        events,
        lastProcessedEventRef.current,
        nextNoticeIndexRef.current,
      );

      lastProcessedEventRef.current = next.lastProcessedEvent;
      nextNoticeIndexRef.current = next.nextNoticeIndex;
      return next.notices;
    });
  }, [events]);

  return notices;
}
