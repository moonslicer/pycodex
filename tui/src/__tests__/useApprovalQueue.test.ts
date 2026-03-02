import {
  INITIAL_APPROVAL_QUEUE_STATE,
  approvalQueueReducer,
  classifyApprovalRequest,
  maybeAutoDenyOverflowedApprovalRequest,
  reduceApprovalQueue,
  sendApprovalResponseForRequest,
} from "../hooks/useApprovalQueue.js";

function applyEvents(
  events: Parameters<typeof reduceApprovalQueue>[1][],
): ReturnType<typeof reduceApprovalQueue> {
  let state = INITIAL_APPROVAL_QUEUE_STATE;
  for (const event of events) {
    state = reduceApprovalQueue(state, event);
  }
  return state;
}

describe("reduceApprovalQueue", () => {
  test("approval.request enqueues a request", () => {
    const next = reduceApprovalQueue(INITIAL_APPROVAL_QUEUE_STATE, {
      type: "approval.request",
      thread_id: "thread_1",
      turn_id: "turn_1",
      request_id: "req_1",
      tool: "write_file",
      preview: "{}",
    });

    expect(next.queue).toHaveLength(1);
    expect(next.queue[0]?.request_id).toBe("req_1");
  });

  test("non approval events are ignored", () => {
    const next = reduceApprovalQueue(INITIAL_APPROVAL_QUEUE_STATE, {
      type: "turn.started",
      thread_id: "thread_1",
      turn_id: "turn_1",
    });

    expect(next).toBe(INITIAL_APPROVAL_QUEUE_STATE);
  });

  test("duplicate request_id is ignored", () => {
    const started = reduceApprovalQueue(INITIAL_APPROVAL_QUEUE_STATE, {
      type: "approval.request",
      thread_id: "thread_1",
      turn_id: "turn_1",
      request_id: "req_1",
      tool: "write_file",
      preview: "{}",
    });

    const duplicate = reduceApprovalQueue(started, {
      type: "approval.request",
      thread_id: "thread_1",
      turn_id: "turn_1",
      request_id: "req_1",
      tool: "shell",
      preview: "{\"cmd\":\"pwd\"}",
    });

    expect(duplicate).toBe(started);
  });

  test("queue overflow keeps state unchanged", () => {
    let state = INITIAL_APPROVAL_QUEUE_STATE;
    for (let index = 0; index < 100; index += 1) {
      state = reduceApprovalQueue(state, {
        type: "approval.request",
        thread_id: "thread_1",
        turn_id: "turn_1",
        request_id: `req_${String(index)}`,
        tool: "write_file",
        preview: "{}",
      });
    }
    expect(state.queue).toHaveLength(100);

    const next = reduceApprovalQueue(state, {
      type: "approval.request",
      thread_id: "thread_1",
      turn_id: "turn_1",
      request_id: "req_overflow",
      tool: "write_file",
      preview: "{}",
    });

    expect(next).toBe(state);
  });
});

describe("classifyApprovalRequest", () => {
  test("returns duplicate for existing request id", () => {
    const state = reduceApprovalQueue(INITIAL_APPROVAL_QUEUE_STATE, {
      type: "approval.request",
      thread_id: "thread_1",
      turn_id: "turn_1",
      request_id: "req_1",
      tool: "write_file",
      preview: "{}",
    });

    expect(classifyApprovalRequest(state, { request_id: "req_1" })).toBe(
      "duplicate",
    );
  });

  test("returns overflow at max queue size", () => {
    let state = INITIAL_APPROVAL_QUEUE_STATE;
    for (let index = 0; index < 100; index += 1) {
      state = reduceApprovalQueue(state, {
        type: "approval.request",
        thread_id: "thread_1",
        turn_id: "turn_1",
        request_id: `req_${String(index)}`,
        tool: "write_file",
        preview: "{}",
      });
    }

    expect(classifyApprovalRequest(state, { request_id: "req_100" })).toBe(
      "overflow",
    );
  });
});

describe("maybeAutoDenyOverflowedApprovalRequest", () => {
  test("sends denied response when queue is full", () => {
    const sendApprovalResponse = jest.fn();
    const writer = { sendApprovalResponse };
    let state = INITIAL_APPROVAL_QUEUE_STATE;
    for (let index = 0; index < 100; index += 1) {
      state = reduceApprovalQueue(state, {
        type: "approval.request",
        thread_id: "thread_1",
        turn_id: "turn_1",
        request_id: `req_${String(index)}`,
        tool: "write_file",
        preview: "{}",
      });
    }

    const didAutoDeny = maybeAutoDenyOverflowedApprovalRequest(
      writer,
      state,
      { request_id: "req_overflow" },
    );

    expect(didAutoDeny).toBe(true);
    expect(sendApprovalResponse).toHaveBeenCalledWith("req_overflow", "denied");
  });

  test("returns false when queue has capacity", () => {
    const sendApprovalResponse = jest.fn();
    const writer = { sendApprovalResponse };
    const didAutoDeny = maybeAutoDenyOverflowedApprovalRequest(
      writer,
      INITIAL_APPROVAL_QUEUE_STATE,
      { request_id: "req_1" },
    );
    expect(didAutoDeny).toBe(false);
    expect(sendApprovalResponse).not.toHaveBeenCalled();
  });
});

describe("approvalQueueReducer", () => {
  test("dequeue removes only the queue head", () => {
    const withFirst = reduceApprovalQueue(INITIAL_APPROVAL_QUEUE_STATE, {
      type: "approval.request",
      thread_id: "thread_1",
      turn_id: "turn_1",
      request_id: "req_1",
      tool: "write_file",
      preview: "{}",
    });
    const withSecond = reduceApprovalQueue(withFirst, {
      type: "approval.request",
      thread_id: "thread_1",
      turn_id: "turn_1",
      request_id: "req_2",
      tool: "shell",
      preview: "{}",
    });

    const ignored = approvalQueueReducer(withSecond, {
      type: "dequeue",
      request_id: "req_2",
    });
    expect(ignored).toBe(withSecond);

    const dequeued = approvalQueueReducer(withSecond, {
      type: "dequeue",
      request_id: "req_1",
    });
    expect(dequeued.queue).toHaveLength(1);
    expect(dequeued.queue[0]?.request_id).toBe("req_2");
  });
});

describe("integration: event stream → queue → respond → dequeue", () => {
  test("full approval flow: enqueue, respond, dequeue", () => {
    const sendApprovalResponse = jest.fn();
    const writer = { sendApprovalResponse };

    // 1. Turn starts, approval requested
    let state = applyEvents([
      { type: "turn.started", thread_id: "t1", turn_id: "turn_1" },
      {
        type: "approval.request",
        thread_id: "t1",
        turn_id: "turn_1",
        request_id: "req_1",
        tool: "shell",
        preview: "{}",
      },
    ]);
    expect(state.queue).toHaveLength(1);
    expect(state.queue[0]?.request_id).toBe("req_1");

    // 2. User responds via respond()
    const currentRequest = state.queue[0] ?? null;
    const requestId = sendApprovalResponseForRequest(
      writer,
      currentRequest,
      "approved",
    );
    expect(requestId).toBe("req_1");
    expect(sendApprovalResponse).toHaveBeenCalledWith("req_1", "approved");

    // 3. Dequeue
    state = approvalQueueReducer(state, {
      type: "dequeue",
      request_id: "req_1",
    });
    expect(state.queue).toHaveLength(0);
  });

  test("turn.completed flushes all queued requests for that turn", () => {
    let state = applyEvents([
      {
        type: "approval.request",
        thread_id: "t1",
        turn_id: "turn_1",
        request_id: "req_1",
        tool: "shell",
        preview: "{}",
      },
      {
        type: "approval.request",
        thread_id: "t1",
        turn_id: "turn_1",
        request_id: "req_2",
        tool: "read_file",
        preview: "{}",
      },
    ]);
    expect(state.queue).toHaveLength(2);

    state = reduceApprovalQueue(state, {
      type: "turn.completed",
      thread_id: "t1",
      turn_id: "turn_1",
      final_text: "",
      usage: {
        turn: { input_tokens: 0, output_tokens: 0 },
        cumulative: { input_tokens: 0, output_tokens: 0 },
      },
    });
    expect(state.queue).toHaveLength(0);
  });

  test("turn.failed flushes only requests for that turn, not others", () => {
    let state = applyEvents([
      {
        type: "approval.request",
        thread_id: "t1",
        turn_id: "turn_1",
        request_id: "req_1",
        tool: "shell",
        preview: "{}",
      },
      {
        type: "approval.request",
        thread_id: "t1",
        turn_id: "turn_2",
        request_id: "req_2",
        tool: "read_file",
        preview: "{}",
      },
    ]);
    expect(state.queue).toHaveLength(2);

    state = reduceApprovalQueue(state, {
      type: "turn.failed",
      thread_id: "t1",
      turn_id: "turn_1",
      error: "interrupted",
    });
    expect(state.queue).toHaveLength(1);
    expect(state.queue[0]?.request_id).toBe("req_2");
  });
});

describe("sendApprovalResponseForRequest", () => {
  test("writes approval.response for current request", () => {
    const sendApprovalResponse = jest.fn();
    const writer = {
      sendApprovalResponse,
    };

    const requestId = sendApprovalResponseForRequest(
      writer,
      {
        thread_id: "thread_1",
        turn_id: "turn_1",
        request_id: "req_1",
        tool: "write_file",
        preview: "{}",
      },
      "approved",
    );

    expect(requestId).toBe("req_1");
    expect(sendApprovalResponse).toHaveBeenCalledWith("req_1", "approved");
  });

  test("no-op when request is null", () => {
    const sendApprovalResponse = jest.fn();
    const writer = {
      sendApprovalResponse,
    };

    const requestId = sendApprovalResponseForRequest(
      writer,
      null,
      "approved",
    );

    expect(requestId).toBeNull();
    expect(sendApprovalResponse).not.toHaveBeenCalled();
  });
});
