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
        estimated_prompt_tokens: 11,
        context_window_tokens: 128000,
        compaction_count: 1,
      },
      expected:
        "Session thread_1: turns=2 tokens(in/out)=15/9 context_window=128000 compacted=1",
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
    const unrelatedEvents: ProtocolEvent[] = [
      {
        type: "thread.started",
        thread_id: "thread_1",
      },
    ];

    for (const event of unrelatedEvents) {
      expect(toSystemNoticeText(event)).toBeNull();
    }
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
        estimated_prompt_tokens: 8,
        context_window_tokens: 128000,
        compaction_count: 0,
      },
      {
        type: "slash.unknown",
        command: "wat",
      },
    ];

    const next = updateSystemNotices([], events, null, 1);

    expect(next.notices).toEqual<SystemNotice[]>([
      {
        id: "notice_status",
        text:
          "Session thread_1: turns=1 tokens(in/out)=10/5 context_window=128000 compacted=0",
      },
      {
        id: "notice_1",
        text: "Unknown command: /wat",
      },
    ]);
    expect(next.nextNoticeIndex).toBe(2);
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
      type: "thread.started",
      thread_id: "thread_1",
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
        text: "Unknown command: /first",
      },
    ];

    const next = updateSystemNotices(
      existingNotices,
      allEvents,
      second,
      2,
    );

    expect(next.notices).toEqual<SystemNotice[]>([
      ...existingNotices,
      {
        id: "notice_2",
        text: "Session list failed: boom",
      },
    ]);
    expect(next.nextNoticeIndex).toBe(3);
    expect(next.lastProcessedEvent).toBe(third);
  });

  test("upserts session.status as one rolling notice", () => {
    const firstStatus: ProtocolEvent = {
      type: "session.status",
      thread_id: "thread_1",
      turn_count: 1,
      input_tokens: 10,
      output_tokens: 5,
      estimated_prompt_tokens: 8,
      context_window_tokens: 128000,
      compaction_count: 0,
    };
    const secondStatus: ProtocolEvent = {
      type: "session.status",
      thread_id: "thread_1",
      turn_count: 2,
      input_tokens: 20,
      output_tokens: 10,
      estimated_prompt_tokens: 16,
      context_window_tokens: 128000,
      compaction_count: 1,
    };

    const once = updateSystemNotices([], [firstStatus], null, 1);
    const twice = updateSystemNotices(once.notices, [firstStatus, secondStatus], firstStatus, 1);

    expect(twice.notices).toEqual<SystemNotice[]>([
      {
        id: "notice_status",
        text:
          "Session thread_1: turns=2 tokens(in/out)=20/10 context_window=128000 compacted=1",
      },
    ]);
    expect(twice.nextNoticeIndex).toBe(1);
    expect(twice.lastProcessedEvent).toBe(secondStatus);
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
