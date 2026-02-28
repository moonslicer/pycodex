import { PassThrough } from "node:stream";
import { EventEmitter } from "node:events";
import type { ChildProcess } from "node:child_process";

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
  test("dispatches valid protocol events", async () => {
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
        type: "turn.completed",
        thread_id: "thread_1",
        turn_id: "turn_1",
        final_text: "done",
        usage: null,
      })}\n`,
    );

    await waitForAsyncDispatch();

    expect(seenTypes).toEqual(["thread.started", "turn.completed"]);
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
