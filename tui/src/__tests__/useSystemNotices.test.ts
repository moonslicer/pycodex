import type { ProtocolEvent } from "../protocol/types.js";
import {
  toSystemNoticeText,
  updateSystemNotices,
  type SystemNotice,
} from "../hooks/useSystemNotices.js";

describe("toSystemNoticeText", () => {
  test.each([
    {
      event: {
        type: "session.status" as const,
        thread_id: "thread_1",
        turn_count: 2,
        input_tokens: 15,
        output_tokens: 9,
      },
      expected:
        "Session thread_1: turns=2 tokens(in/out)=15/9",
    },
    {
      event: {
        type: "slash.unknown" as const,
        command: "bogus",
      },
      expected: "Unknown command: /bogus",
    },
    {
      event: {
        type: "slash.blocked" as const,
        command: "resume",
        reason: "active_turn" as const,
      },
      expected: "Blocked: /resume cannot run during an active turn.",
    },
    {
      event: {
        type: "session.error" as const,
        operation: "resume" as const,
        message: "not found",
      },
      expected: "Session resume failed: not found",
    },
  ])("formats $event.type", ({ event, expected }) => {
    expect(toSystemNoticeText(event as ProtocolEvent)).toBe(expected);
  });

  test("returns null for unrelated events", () => {
    expect(
      toSystemNoticeText({
        type: "thread.started",
        thread_id: "thread_1",
      }),
    ).toBeNull();
  });
});

describe("updateSystemNotices", () => {
  test("accumulates notices from supported events", () => {
    const events: ProtocolEvent[] = [
      {
        type: "session.status",
        thread_id: "thread_1",
        turn_count: 1,
        input_tokens: 10,
        output_tokens: 5,
      },
      {
        type: "slash.unknown",
        command: "wat",
      },
    ];

    const next = updateSystemNotices([], events, null, 1);

    expect(next.notices).toEqual<SystemNotice[]>([
      {
        id: "notice_1",
        text: "Session thread_1: turns=1 tokens(in/out)=10/5",
      },
      {
        id: "notice_2",
        text: "Unknown command: /wat",
      },
    ]);
    expect(next.nextNoticeIndex).toBe(3);
    expect(next.lastProcessedEvent).toBe(events[1]);
  });

  test("ignores unsupported events", () => {
    const events: ProtocolEvent[] = [
      {
        type: "thread.started",
        thread_id: "thread_1",
      },
    ];

    const next = updateSystemNotices([], events, null, 1);

    expect(next.notices).toEqual([]);
    expect(next.nextNoticeIndex).toBe(1);
    expect(next.lastProcessedEvent).toBe(events[0]);
  });

  test("processes only events after the last processed event", () => {
    const first: ProtocolEvent = {
      type: "session.status",
      thread_id: "thread_1",
      turn_count: 1,
      input_tokens: 10,
      output_tokens: 5,
    };
    const second: ProtocolEvent = {
      type: "slash.unknown",
      command: "first",
    };
    const third: ProtocolEvent = {
      type: "session.error",
      operation: "list",
      message: "boom",
    };

    const allEvents: ProtocolEvent[] = [first, second, third];
    const existingNotices: SystemNotice[] = [
      {
        id: "notice_1",
        text: "Session thread_1: turns=1 tokens(in/out)=10/5",
      },
      {
        id: "notice_2",
        text: "Unknown command: /first",
      },
    ];

    const next = updateSystemNotices(
      existingNotices,
      allEvents,
      second,
      3,
    );

    expect(next.notices).toEqual<SystemNotice[]>([
      ...existingNotices,
      {
        id: "notice_3",
        text: "Session list failed: boom",
      },
    ]);
    expect(next.nextNoticeIndex).toBe(4);
    expect(next.lastProcessedEvent).toBe(third);
  });

  test("clears notices when events reset to empty", () => {
    const existingNotices: SystemNotice[] = [
      {
        id: "notice_7",
        text: "Unknown command: /wat",
      },
    ];
    const lastProcessedEvent: ProtocolEvent = {
      type: "slash.unknown",
      command: "wat",
    };

    const next = updateSystemNotices(
      existingNotices,
      [],
      lastProcessedEvent,
      8,
    );

    expect(next).toEqual({
      notices: [],
      lastProcessedEvent: null,
      nextNoticeIndex: 1,
    });
  });
});
