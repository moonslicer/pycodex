import { EventEmitter } from "node:events";
import type { ChildProcess } from "node:child_process";
import { PassThrough } from "node:stream";

import { StdioReader } from "../protocol/transports/stdio.js";

class MockChildProcess extends EventEmitter {
  public readonly stdout = new PassThrough();
  public readonly stdin = new PassThrough();
}

function createChildProcess(): {
  child: ChildProcess;
  stdout: PassThrough;
} {
  const mock = new MockChildProcess();
  return {
    child: mock as unknown as ChildProcess,
    stdout: mock.stdout,
  };
}

function waitForAsyncDispatch(): Promise<void> {
  return new Promise((resolve) => {
    setImmediate(() => {
      resolve();
    });
  });
}

describe("StdioReader", () => {
  test("dispatches valid protocol event shapes", async () => {
    const { child, stdout } = createChildProcess();
    const reader = new StdioReader(child);
    const seenTypes: string[] = [];

    reader.onEvent((event) => {
      seenTypes.push(event.type);
    });
    reader.start();

    stdout.write(
      `${JSON.stringify({ type: "thread.started", thread_id: "thread_1" })}\n`,
    );
    stdout.write(
      `${JSON.stringify({
        type: "item.started",
        thread_id: "thread_1",
        turn_id: "turn_1",
        item_id: "item_1",
        item_kind: "tool_call",
        name: "list_dir",
        arguments: '{"path":"."}',
      })}\n`,
    );
    stdout.write(
      `${JSON.stringify({
        type: "item.updated",
        thread_id: "thread_1",
        turn_id: "turn_1",
        item_id: "item_2",
        delta: "streaming text",
      })}\n`,
    );
    stdout.write(
      `${JSON.stringify({
        type: "context.compacted",
        thread_id: "thread_1",
        turn_id: "turn_1",
        strategy: "threshold_v1",
        implementation: "local_summary_v1",
        replaced_items: 5,
        estimated_prompt_tokens: 9100,
        context_window_tokens: 10000,
        remaining_ratio: 0.09,
        threshold_ratio: 0.2,
      })}\n`,
    );
    stdout.write(
      `${JSON.stringify({
        type: "approval.request",
        thread_id: "thread_1",
        turn_id: "turn_1",
        request_id: "req_1",
        tool: "write_file",
        preview: '{"arg_count":1,"arg_keys":["file_path"]}',
      })}\n`,
    );

    await waitForAsyncDispatch();

    expect(seenTypes).toEqual([
      "thread.started",
      "item.started",
      "item.updated",
      "context.compacted",
      "approval.request",
    ]);
  });

  test("dispatches new session and slash event shapes", async () => {
    const { child, stdout } = createChildProcess();
    const reader = new StdioReader(child);
    const seenTypes: string[] = [];

    reader.onEvent((event) => {
      seenTypes.push(event.type);
    });
    reader.start();

    stdout.write(
      `${JSON.stringify({
        type: "session.listed",
        sessions: [],
      })}\n`,
    );
    stdout.write(
      `${JSON.stringify({
        type: "session.listed",
        sessions: [
          {
            thread_id: "thread_1",
            status: "closed",
            turn_count: 1,
            token_total: 2,
            last_user_message: "hello",
            date: "2026-03-06",
          },
          { broken: true },
        ],
      })}\n`,
    );
    stdout.write(
      `${JSON.stringify({
        type: "session.status",
        thread_id: "thread_1",
        turn_count: 1,
        input_tokens: 12,
        output_tokens: 7,
      })}\n`,
    );
    stdout.write(
      `${JSON.stringify({
        type: "slash.unknown",
        command: "bogus",
      })}\n`,
    );
    stdout.write(
      `${JSON.stringify({
        type: "slash.blocked",
        command: "resume",
        reason: "active_turn",
      })}\n`,
    );
    stdout.write(
      `${JSON.stringify({
        type: "session.error",
        operation: "resume",
        message: "not found",
      })}\n`,
    );

    await waitForAsyncDispatch();

    expect(seenTypes).toEqual([
      "session.listed",
      "session.listed",
      "session.status",
      "slash.unknown",
      "slash.blocked",
      "session.error",
    ]);
  });

  test("rejects session.listed when sessions is not an array", async () => {
    const { child, stdout } = createChildProcess();
    const reader = new StdioReader(child);
    const seenTypes: string[] = [];

    reader.onEvent((event) => {
      seenTypes.push(event.type);
    });
    reader.start();

    stdout.write(
      `${JSON.stringify({
        type: "session.listed",
        sessions: "not-an-array",
      })}\n`,
    );

    await waitForAsyncDispatch();

    expect(seenTypes).toEqual([]);
  });

  test("accepts item.started with nullable optional fields", async () => {
    const { child, stdout } = createChildProcess();
    const reader = new StdioReader(child);
    const seenTypes: string[] = [];

    reader.onEvent((event) => {
      seenTypes.push(event.type);
    });
    reader.start();

    stdout.write(
      `${JSON.stringify({
        type: "item.started",
        thread_id: "thread_1",
        turn_id: "turn_1",
        item_id: "item_1",
        item_kind: "tool_call",
        name: null,
        arguments: null,
      })}\n`,
    );

    await waitForAsyncDispatch();

    expect(seenTypes).toEqual(["item.started"]);
  });

  test("ignores malformed and unknown payloads without crashing", async () => {
    const { child, stdout } = createChildProcess();
    const reader = new StdioReader(child);
    const seenTypes: string[] = [];

    reader.onEvent((event) => {
      seenTypes.push(event.type);
    });
    reader.start();

    stdout.write("{not-json}\n");
    stdout.write(`${JSON.stringify({ type: "unknown.event" })}\n`);
    stdout.write(
      `${JSON.stringify({ type: "turn.started", thread_id: "thread_1" })}\n`,
    );

    await waitForAsyncDispatch();

    expect(seenTypes).toEqual([]);
  });

  test("emits close handlers once when stdout closes", async () => {
    const { child, stdout } = createChildProcess();
    const reader = new StdioReader(child);
    let closeCount = 0;

    reader.onClose(() => {
      closeCount += 1;
    });
    reader.start();

    stdout.end();
    await waitForAsyncDispatch();

    expect(closeCount).toBe(1);
  });
});
