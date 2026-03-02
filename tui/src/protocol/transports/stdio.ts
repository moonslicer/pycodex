import type { ChildProcess } from "node:child_process";
import { createInterface, type Interface } from "node:readline";

import type { ProtocolReader } from "../reader.js";
import type { ProtocolWriter } from "../writer.js";
import type {
  ApprovalDecision,
  Command,
  ProtocolEvent,
  TokenUsage,
  UsageSnapshot,
} from "../types.js";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isTokenUsage(value: unknown): value is TokenUsage {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value["input_tokens"] === "number" &&
    typeof value["output_tokens"] === "number"
  );
}

function isUsageSnapshot(value: unknown): value is UsageSnapshot {
  if (!isRecord(value)) {
    return false;
  }
  return isTokenUsage(value["turn"]) && isTokenUsage(value["cumulative"]);
}

function isProtocolEvent(value: unknown): value is ProtocolEvent {
  if (!isRecord(value) || !isString(value["type"])) {
    return false;
  }

  const type = value["type"];
  const threadId = value["thread_id"];
  const turnId = value["turn_id"];
  const itemId = value["item_id"];

  switch (type) {
    case "thread.started":
      return isString(threadId);
    case "turn.started":
      return isString(threadId) && isString(turnId);
    case "turn.completed":
      return (
        isString(threadId) &&
        isString(turnId) &&
        isString(value["final_text"]) &&
        (value["usage"] === null || isUsageSnapshot(value["usage"]))
      );
    case "turn.failed":
      return (
        isString(threadId) && isString(turnId) && isString(value["error"])
      );
    case "item.started":
      if (
        !isString(threadId) ||
        !isString(turnId) ||
        !isString(itemId) ||
        (value["item_kind"] !== "tool_call" &&
          value["item_kind"] !== "assistant_message")
      ) {
        return false;
      }
      if (
        "name" in value &&
        value["name"] !== undefined &&
        value["name"] !== null &&
        !isString(value["name"])
      ) {
        return false;
      }
      if (
        "arguments" in value &&
        value["arguments"] !== undefined &&
        value["arguments"] !== null &&
        !isString(value["arguments"])
      ) {
        return false;
      }
      return true;
    case "item.completed":
      return (
        isString(threadId) &&
        isString(turnId) &&
        isString(itemId) &&
        (value["item_kind"] === "tool_result" ||
          value["item_kind"] === "assistant_message") &&
        isString(value["content"])
      );
    case "item.updated":
      return (
        isString(threadId) &&
        isString(turnId) &&
        isString(itemId) &&
        isString(value["delta"])
      );
    case "approval.request":
      return (
        isString(threadId) &&
        isString(turnId) &&
        isString(value["request_id"]) &&
        isString(value["tool"]) &&
        isString(value["preview"])
      );
    default:
      return false;
  }
}

export class StdioReader implements ProtocolReader {
  private readonly eventHandlers = new Set<(event: ProtocolEvent) => void>();
  private readonly closeHandlers = new Set<() => void>();
  private lineReader: Interface | null = null;
  private didEmitClose = false;

  constructor(private readonly child: ChildProcess) {}

  start(): void {
    if (this.lineReader !== null) {
      return;
    }

    const stdout = this.child.stdout;
    if (stdout === null) {
      process.stderr.write("[tui] child stdout is unavailable\n");
      this.emitClose();
      return;
    }

    const lineReader = createInterface({
      input: stdout,
      crlfDelay: Infinity,
    });

    this.lineReader = lineReader;

    lineReader.on("line", (line) => {
      this.handleLine(line);
    });
    lineReader.on("close", () => {
      this.emitClose();
    });
    // Fix #2: handle encoding/stream errors on the readline interface
    lineReader.on("error", () => {
      this.emitClose();
    });

    // Fix #1: handle child process spawn/runtime errors
    this.child.on("error", () => {
      this.emitClose();
    });

    // Fix #3: drain child stderr to prevent buffer fill causing child to hang
    if (this.child.stderr) {
      this.child.stderr.pipe(process.stderr);
    }

    this.child.once("exit", () => {
      this.emitClose();
    });
  }

  onEvent(handler: (event: ProtocolEvent) => void): () => void {
    this.eventHandlers.add(handler);
    return () => {
      this.eventHandlers.delete(handler);
    };
  }

  onClose(handler: () => void): () => void {
    this.closeHandlers.add(handler);
    return () => {
      this.closeHandlers.delete(handler);
    };
  }

  private handleLine(line: string): void {
    const trimmed = line.trim();
    if (trimmed.length === 0) {
      return;
    }

    let parsed: unknown;
    try {
      parsed = JSON.parse(trimmed);
    } catch {
      process.stderr.write(`[tui] malformed event: ${trimmed}\n`);
      return;
    }

    if (!isProtocolEvent(parsed)) {
      process.stderr.write("[tui] ignored unknown or invalid event payload\n");
      return;
    }

    for (const handler of this.eventHandlers) {
      handler(parsed);
    }
  }

  private emitClose(): void {
    if (this.didEmitClose) {
      return;
    }

    this.didEmitClose = true;

    // Fix #4: close the readline interface to release resources
    if (this.lineReader !== null) {
      this.lineReader.close();
    }

    for (const handler of this.closeHandlers) {
      handler();
    }
  }
}

export class StdioWriter implements ProtocolWriter {
  constructor(private readonly child: ChildProcess) {}

  sendUserInput(text: string): void {
    this.write({
      jsonrpc: "2.0",
      method: "user.input",
      params: { text },
    });
  }

  sendApprovalResponse(requestId: string, decision: ApprovalDecision): void {
    this.write({
      jsonrpc: "2.0",
      method: "approval.response",
      params: { request_id: requestId, decision },
    });
  }

  sendInterrupt(): void {
    this.write({
      jsonrpc: "2.0",
      method: "interrupt",
      params: {},
    });
  }

  close(): void {
    const stdin = this.child.stdin;
    if (stdin !== null && !stdin.writableEnded) {
      stdin.end();
    }
  }

  private write(command: Command): void {
    const stdin = this.child.stdin;
    if (
      stdin === null || stdin.destroyed || stdin.writableEnded
    ) {
      return;
    }

    stdin.write(`${JSON.stringify(command)}\n`);
  }
}
