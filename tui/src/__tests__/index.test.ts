import type { ChildProcess } from "node:child_process";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";

import type { ProtocolReader } from "../protocol/reader.js";
import type { ProtocolWriter } from "../protocol/writer.js";
import { isSupportedEntrypointPath, main } from "../index.js";

class MockChildProcess extends EventEmitter {
  public readonly stdout = new PassThrough();
  public readonly stdin = new PassThrough();
  public readonly stderr = new PassThrough();
  public exitCode: number | null = null;
  public readonly killCalls: Array<NodeJS.Signals | number | undefined> = [];

  kill(signal?: NodeJS.Signals | number): boolean {
    this.killCalls.push(signal);
    return true;
  }
}

class MockReader implements ProtocolReader {
  public startCount = 0;
  private readonly closeHandlers = new Set<() => void>();

  start(): void {
    this.startCount += 1;
  }

  onEvent(): () => void {
    return () => {};
  }

  onClose(handler: () => void): () => void {
    this.closeHandlers.add(handler);
    return () => {
      this.closeHandlers.delete(handler);
    };
  }

  emitClose(): void {
    for (const handler of this.closeHandlers) {
      handler();
    }
  }
}

class MockWriter implements ProtocolWriter {
  public readonly userInputs: string[] = [];
  public readonly approvalResponses: Array<{
    requestId: string;
    decision: "approved" | "approved_for_session" | "denied" | "abort";
  }> = [];
  public interruptCount = 0;
  public closeCount = 0;

  sendUserInput(text: string): void {
    this.userInputs.push(text);
  }

  sendApprovalResponse(
    requestId: string,
    decision: "approved" | "approved_for_session" | "denied" | "abort",
  ): void {
    this.approvalResponses.push({ requestId, decision });
  }

  sendInterrupt(): void {
    this.interruptCount += 1;
  }

  close(): void {
    this.closeCount += 1;
  }
}

class MockProcessRef {
  public readonly argv = ["node", "/tmp/tui/index.js"];
  public readonly env: NodeJS.ProcessEnv = {};
  public readonly exitCalls: Array<number | undefined> = [];
  public readonly stderrMessages: string[] = [];

  private readonly signalHandlers = new Map<"SIGINT" | "SIGTERM", () => void>();

  public readonly stderr = {
    write: (message: string) => {
      this.stderrMessages.push(message);
      return true;
    },
  };

  once(signal: "SIGINT" | "SIGTERM", listener: () => void): void {
    this.signalHandlers.set(signal, listener);
  }

  exit(code?: number): void {
    this.exitCalls.push(code);
  }

  emitSignal(signal: "SIGINT" | "SIGTERM"): void {
    const listener = this.signalHandlers.get(signal);
    if (listener === undefined) {
      return;
    }
    this.signalHandlers.delete(signal);
    listener();
  }
}

type MainHarness = {
  child: MockChildProcess;
  processRef: MockProcessRef;
  reader: MockReader;
  writer: MockWriter;
  renderUnmountCount: number;
};

function createHarness(): MainHarness {
  return {
    child: new MockChildProcess(),
    processRef: new MockProcessRef(),
    reader: new MockReader(),
    writer: new MockWriter(),
    renderUnmountCount: 0,
  };
}

describe("index main lifecycle", () => {
  test("supports current compiled entrypoint path", () => {
    expect(
      isSupportedEntrypointPath(
        "/Users/example/project/tui/dist/src/index.js",
      ),
    ).toBe(true);
    expect(
      isSupportedEntrypointPath(
        "/Users/example/project/tui/src/index.ts",
      ),
    ).toBe(true);
    expect(
      isSupportedEntrypointPath(
        "/Users/example/project/tui/dist/other.js",
      ),
    ).toBe(false);
  });

  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  test("reader close + child exit performs deterministic single shutdown", () => {
    const harness = createHarness();

    const spawnCalls: Array<{
      command: string;
      args: readonly string[];
      cwd: string;
    }> = [];
    const spawnProcess = (
      command: string,
      args: readonly string[],
      options: { cwd: string },
    ) => {
      spawnCalls.push({ command, args, cwd: options.cwd });
      return harness.child as unknown as ChildProcess;
    };

    main({
      resolveRepoRoot: () => "/repo/root",
      spawnProcess,
      buildPycodexArgs: () => ["-m", "pycodex", "--tui-mode"],
      makeReader: () => harness.reader,
      makeWriter: () => harness.writer,
      renderApp: () => ({
        unmount: () => {
          harness.renderUnmountCount += 1;
        },
      }),
      processRef: harness.processRef,
    });

    expect(spawnCalls).toEqual([
      {
        command: "python3",
        args: ["-m", "pycodex", "--tui-mode"],
        cwd: "/repo/root",
      },
    ]);
    expect(harness.reader.startCount).toBe(1);

    harness.reader.emitClose();

    expect(harness.writer.closeCount).toBe(1);
    expect(harness.child.killCalls).toContain("SIGTERM");

    harness.child.exitCode = 0;
    harness.child.emit("exit", 0, null);

    expect(harness.renderUnmountCount).toBe(1);
    expect(harness.processRef.exitCalls).toEqual([0]);

    harness.reader.emitClose();
    expect(harness.writer.closeCount).toBe(1);
    expect(harness.processRef.exitCalls).toEqual([0]);
  });

  test("SIGINT requests interrupt once and exits with child code", () => {
    const harness = createHarness();

    main({
      resolveRepoRoot: () => "/repo/root",
      spawnProcess: () => harness.child as unknown as ChildProcess,
      buildPycodexArgs: () => ["-m", "pycodex", "--tui-mode"],
      makeReader: () => harness.reader,
      makeWriter: () => harness.writer,
      renderApp: () => ({
        unmount: () => {
          harness.renderUnmountCount += 1;
        },
      }),
      processRef: harness.processRef,
    });

    harness.processRef.emitSignal("SIGINT");
    harness.processRef.emitSignal("SIGINT");

    expect(harness.writer.interruptCount).toBe(1);
    expect(harness.writer.closeCount).toBe(1);
    expect(harness.child.killCalls).toContain("SIGTERM");

    harness.child.exitCode = 130;
    harness.child.emit("exit", 130, null);

    expect(harness.processRef.exitCalls).toEqual([130]);
  });

  test("exit arriving before render assignment still unmounts once", () => {
    const harness = createHarness();

    let renderCalls = 0;
    const renderApp = () => {
      renderCalls += 1;
      harness.child.exitCode = 0;
      harness.child.emit("exit", 0, null);
      return {
        unmount: () => {
          harness.renderUnmountCount += 1;
        },
      };
    };

    main({
      resolveRepoRoot: () => "/repo/root",
      spawnProcess: () => harness.child as unknown as ChildProcess,
      buildPycodexArgs: () => ["-m", "pycodex", "--tui-mode"],
      makeReader: () => harness.reader,
      makeWriter: () => harness.writer,
      renderApp,
      processRef: harness.processRef,
    });

    expect(renderCalls).toBe(1);
    expect(harness.renderUnmountCount).toBe(1);
    expect(harness.processRef.exitCalls).toEqual([0]);
  });
});
