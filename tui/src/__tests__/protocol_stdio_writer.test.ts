import { PassThrough } from "node:stream";
import { EventEmitter } from "node:events";
import type { ChildProcess } from "node:child_process";

import { StdioWriter } from "../protocol/transports/stdio.js";

class MockChildProcess extends EventEmitter {
  public readonly stdout = new PassThrough();
  public readonly stdin = new PassThrough();
}

function createChildProcess(): {
  child: ChildProcess;
  stdin: PassThrough;
} {
  const mock = new MockChildProcess();
  return {
    child: mock as unknown as ChildProcess,
    stdin: mock.stdin,
  };
}

function waitForAsyncDispatch(): Promise<void> {
  return new Promise((resolve) => {
    setImmediate(() => {
      resolve();
    });
  });
}

describe("StdioWriter", () => {
  test("writes JSON-RPC lines for supported commands", async () => {
    const { child, stdin } = createChildProcess();
    const writer = new StdioWriter(child);
    const writtenChunks: string[] = [];

    stdin.setEncoding("utf8");
    stdin.on("data", (chunk: string) => {
      writtenChunks.push(chunk);
    });

    writer.sendUserInput("hello");
    writer.sendApprovalResponse("req_1", "approved_for_session");
    writer.sendInterrupt();

    await waitForAsyncDispatch();

    const lines = writtenChunks.join("").trimEnd().split("\n");
    expect(lines).toHaveLength(3);

    expect(JSON.parse(lines[0] ?? "")).toEqual({
      jsonrpc: "2.0",
      method: "user.input",
      params: { text: "hello" },
    });
    expect(JSON.parse(lines[1] ?? "")).toEqual({
      jsonrpc: "2.0",
      method: "approval.response",
      params: { request_id: "req_1", decision: "approved_for_session" },
    });
    expect(JSON.parse(lines[2] ?? "")).toEqual({
      jsonrpc: "2.0",
      method: "interrupt",
      params: {},
    });
  });

  test("close ends stdin", () => {
    const { child, stdin } = createChildProcess();
    const writer = new StdioWriter(child);

    writer.close();

    expect(stdin.writableEnded).toBe(true);
  });
});
