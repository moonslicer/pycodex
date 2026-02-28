# PyCodex TUI Plan — M4: Interactive Terminal UI

## Overview

This plan breaks Milestone 4 into four focused sub-milestones using **TypeScript + React + Ink + Yoga** as the display layer. Each sub-milestone produces a runnable, testable system. You can stop at any point and have a coherent codebase.

**Core insight**: The JSON-RPC envelope over stdio pipes is intentionally transport-agnostic. In M4 it runs over pipes. In M6 the identical envelope runs over WebSocket — no protocol changes. A future web frontend, VS Code extension, or remote client plugs in as just another transport adapter. The protocol and Python agent are untouched.

---

## Tech Stack Rationale

| Concern | Choice | Why |
|---|---|---|
| UI framework | React 18 + Ink 5 | React component model in terminal; same stack as modern terminal coding UIs; hooks-based state |
| Layout engine | Yoga (via Ink) | CSS Flexbox in terminal; no manual cursor math |
| Language | TypeScript 5 (strict) | Type safety across the protocol boundary; same types mirror Python Pydantic models |
| Testing | Jest + ink-testing-library | Component unit tests without spawning a real TTY |
| Python bridge | asyncio stdin reader | Zero new Python deps; reuses existing M3 JSONL emission |
| Wire protocol | JSON-RPC 2.0 over JSONL | Transport-agnostic; same framing as LSP, MCP; WebSocket swap in M6 is purely mechanical |

**Why not Textual (Python)?** The Python agent already has a clean protocol boundary (M3 JSONL). TypeScript/React/Ink gives us the React component model used by modern terminal coding UIs, proper Flexbox layout via Yoga, and a clear path to web and VS Code extension clients that share the same protocol — not possible from a Python-only TUI.

---

## Repository Structure

```
pycodex/                          ← existing Python package (unchanged except additions below)
│
├── pycodex/
│   ├── __main__.py               ← modify: add --tui-mode flag
│   ├── core/
│   │   ├── tui_bridge.py         ← NEW (M4B): asyncio stdin reader + command dispatcher
│   │   ├── agent.py              ← modify (M4C): surface OutputTextDelta
│   │   └── event_adapter.py      ← modify (M4C): emit ItemUpdated
│   └── protocol/
│       └── events.py             ← modify (M4C, M4D): add ItemUpdated, ApprovalRequested
│
├── tui/                          ← NEW TypeScript package (M4)
│   ├── package.json
│   ├── tsconfig.json
│   ├── jest.config.ts
│   ├── eslint.config.js
│   └── src/
│       ├── index.ts              ← Entry: spawn Python, wire pipes, Ink render
│       ├── app.tsx               ← Root Ink component; owns all top-level state
│       │
│       ├── components/           ← Pure React/Ink UI components
│       │   ├── ChatView.tsx      ← Scrollable message + tool-call history
│       │   ├── InputArea.tsx     ← Single-line prompt input
│       │   ├── StatusBar.tsx     ← Model, turns, token usage, cwd
│       │   ├── ApprovalModal.tsx ← Approval overlay (M4D)
│       │   ├── ToolCallPanel.tsx ← Bordered tool call row (M4E)
│       │   └── Spinner.tsx       ← Animated "thinking" indicator
│       │
│       ├── hooks/                ← Custom React hooks; no UI logic in index.ts or app.tsx
│       │   ├── useProtocolEvents.ts  ← Single canonical reader.onEvent subscription; other hooks derive from it
│       │   ├── useTurns.ts           ← Derives Turn[] state from event stream
│       │   ├── useApprovalQueue.ts   ← Manages pending ApprovalRequest queue
│       │   └── useLineBuffer.ts      ← Newline-gated streaming text buffer
│       │
│       ├── protocol/             ← Transport-agnostic protocol layer
│       │   ├── types.ts          ← TypeScript mirrors of Python Pydantic events + commands
│       │   ├── reader.ts         ← Abstract: ProtocolReader interface
│       │   ├── writer.ts         ← Abstract: ProtocolWriter interface
│       │   └── transports/
│       │       └── stdio.ts      ← Concrete: readline over child.stdout/stdin (M4)
│       │
│       └── __tests__/
│           ├── reader.test.ts
│           ├── writer.test.ts
│           ├── app.test.tsx
│           ├── approvalModal.test.tsx
│           ├── toolCallPanel.test.tsx
│           ├── statusBar.test.tsx
│           ├── useLineBuffer.test.ts
│           ├── useTurns.test.ts
│           └── useApprovalQueue.test.ts
│
└── tests/                        ← existing Python tests
    ├── core/
    │   └── test_tui_bridge.py    ← NEW (M4B)
    └── test_main.py              ← extend (M4B): --tui-mode flag
```

---

## Protocol Layer Design (Transport-Agnostic)

This is the most important architectural decision. The `protocol/` directory is the **only** code that knows about transport. All UI components and Python bridge code talk to abstract interfaces — they never touch `child.stdout` or WebSocket objects directly.

### `protocol/types.ts` — canonical shapes

```typescript
// ── Events: Python → TypeScript (JSONL, one per line) ──────────────────────

export type TokenUsage = {
  input_tokens: number;
  output_tokens: number;
};

export type ProtocolEvent =
  | { type: "thread.started";    thread_id: string }
  | { type: "turn.started";      thread_id: string; turn_id: string }
  | { type: "turn.completed";    thread_id: string; turn_id: string;
      final_text: string; usage: TokenUsage | null }
  | { type: "turn.failed";       thread_id: string; turn_id: string; error: string }
  | { type: "item.started";      thread_id: string; turn_id: string;
      item_id: string; item_kind: "tool_call" | "assistant_message";
      name?: string; arguments?: string }
  | { type: "item.completed";    thread_id: string; turn_id: string;
      item_id: string; item_kind: "tool_result" | "assistant_message"; content: string }
  | { type: "item.updated";      thread_id: string; turn_id: string;
      item_id: string; delta: string }                              // M4C
  | { type: "approval.request";  thread_id: string; turn_id: string;
      request_id: string; tool: string; preview: string }          // M4D

// ── Commands: TypeScript → Python (JSON-RPC 2.0, one per line) ─────────────

export type Command =
  | { jsonrpc: "2.0"; method: "user.input";        params: { text: string } }
  | { jsonrpc: "2.0"; method: "approval.response";
      params: { request_id: string; decision: ApprovalDecision } }
  | { jsonrpc: "2.0"; method: "interrupt";          params: Record<string, never> }

export type ApprovalDecision = "approved" | "denied" | "approved_for_session" | "abort";
```

### `protocol/reader.ts` — abstract interface

```typescript
export interface ProtocolReader {
  /** Subscribe to all incoming ProtocolEvents. Returns unsubscribe fn. */
  onEvent(handler: (event: ProtocolEvent) => void): () => void;
  /** Called once when the underlying transport closes. */
  onClose(handler: () => void): void;
  /** Start reading (for transports that need explicit start). */
  start(): void;
}
```

### `protocol/writer.ts` — abstract interface

```typescript
export interface ProtocolWriter {
  sendUserInput(text: string): void;
  sendApprovalResponse(requestId: string, decision: ApprovalDecision): void;
  sendInterrupt(): void;
  /** Close the write channel (e.g. close stdin). */
  close(): void;
}
```

### `protocol/transports/stdio.ts` — M4 concrete implementation

```typescript
import { createInterface } from "readline";
import { ChildProcess } from "child_process";
import type { ProtocolReader, ProtocolWriter } from "../reader.js";
import type { ProtocolEvent, Command, ApprovalDecision } from "../types.js";

export class StdioReader implements ProtocolReader {
  private handlers: Array<(e: ProtocolEvent) => void> = [];
  private closeHandlers: Array<() => void> = [];

  constructor(private readonly child: ChildProcess) {}

  start(): void {
    const rl = createInterface({ input: this.child.stdout! });
    rl.on("line", (line) => {
      if (!line.trim()) return;
      try {
        const event = JSON.parse(line) as ProtocolEvent;
        this.handlers.forEach((h) => h(event));
      } catch {
        // malformed line — ignore, log to stderr for debugging
        process.stderr.write(`[tui] malformed event: ${line}\n`);
      }
    });
    rl.on("close", () => this.closeHandlers.forEach((h) => h()));
  }

  onEvent(handler: (e: ProtocolEvent) => void): () => void {
    this.handlers.push(handler);
    return () => { this.handlers = this.handlers.filter((h) => h !== handler); };
  }

  onClose(handler: () => void): void { this.closeHandlers.push(handler); }
}

export class StdioWriter implements ProtocolWriter {
  constructor(private readonly child: ChildProcess) {}

  private write(cmd: Command): void {
    this.child.stdin!.write(JSON.stringify(cmd) + "\n");
  }

  sendUserInput(text: string): void {
    this.write({ jsonrpc: "2.0", method: "user.input", params: { text } });
  }

  sendApprovalResponse(requestId: string, decision: ApprovalDecision): void {
    this.write({ jsonrpc: "2.0", method: "approval.response",
                 params: { request_id: requestId, decision } });
  }

  sendInterrupt(): void {
    this.write({ jsonrpc: "2.0", method: "interrupt", params: {} });
  }

  close(): void { this.child.stdin!.end(); }
}
```

> **Note**: `websocket.ts` is not created in M4. The WebSocket transport is planned for M6. Add `tui/src/protocol/transports/websocket.ts` to M6's file table when that milestone is planned.

**Why this matters for future clients**: A web frontend (React in browser), VS Code extension (webview), or remote CLI connects by implementing `ProtocolReader`/`ProtocolWriter` against their own transport (fetch EventSource, postMessage, WebSocket). The Python agent, protocol types, and all UI hook logic are reused without modification.

---

## State Model and Hooks

All application state lives in custom hooks. Components are pure render functions that receive state and callbacks as props — no business logic inside JSX.

### Turn model

```typescript
// tui/src/hooks/useTurns.ts

export type ToolCallState = {
  item_id: string;
  name: string;
  arguments?: string;
  status: "pending" | "done" | "error";
  content?: string;
};

export type TurnState = {
  turn_id: string;
  userText: string;
  assistantLines: string[];      // committed lines (newline-gated from LineBuffer)
  partialLine: string;           // in-progress partial line from item.updated
  toolCalls: Map<string, ToolCallState>;
  status: "active" | "completed" | "failed";
  error?: string;
  usage?: TokenUsage;
};
```

### `useTurns` hook

```typescript
export function useTurns(reader: ProtocolReader): {
  turns: TurnState[];
  threadId: string | null;
} {
  // Subscribes to reader.onEvent.
  // Handles: thread.started, turn.started, turn.completed, turn.failed,
  //          item.started, item.completed, item.updated.
  // Pure state reducer — no side effects, no direct I/O.
}
```

### `useApprovalQueue` hook

```typescript
export type ApprovalRequest = {
  request_id: string;
  tool: string;
  preview: string;
};

export function useApprovalQueue(reader: ProtocolReader, writer: ProtocolWriter): {
  currentRequest: ApprovalRequest | null;
  queueLength: number;
  respond: (decision: ApprovalDecision) => void;
} {
  // Subscribes to approval.request events; queues them.
  // respond() calls writer.sendApprovalResponse and dequeues.
}
```

### `useLineBuffer` hook

```typescript
export function useLineBuffer(): {
  push: (delta: string) => string[];  // returns newly committed lines
  flush: () => string;                // returns remaining partial
  reset: () => void;
} {
  // Accumulates delta strings; splits on \n.
  // Stateless across turns (reset() called on each turn.started).
}
```

### `useProtocolEvents` hook

```typescript
export function useProtocolEvents(reader: ProtocolReader): {
  lastEvent: ProtocolEvent | null;
} {
  // Single canonical subscription to reader.onEvent.
  // useTurns and useApprovalQueue both derive from this rather than
  // independently registering their own reader.onEvent subscriptions.
  // Cleanup (unsubscribe) happens automatically on unmount via useEffect return.
}
```

This is intentionally kept. `useTurns` and `useApprovalQueue` both need the event stream. A single canonical subscription point means one `useEffect` cleanup, one test surface for the subscription contract, and a reuse point for any future hook (status events, debug log, etc.) without duplicating `reader.onEvent` wiring. The hook is ~10 lines — the cost of keeping it is minimal; the cost of wiring subscriptions independently in every consumer hook is not.

---

## Component Architecture

Components are **pure render functions** — they receive typed props, render Ink JSX, and emit typed callbacks. No hooks other than Ink built-ins (`useInput`, `useFocus`) inside components. State management lives in hooks; I/O lives in `index.ts`; components know nothing about transports.

### Component tree

```
<App>                          ← owns reader, writer; passes derived state down
  ├── <ChatView>               ← receives turns[], renders history
  │     ├── <TurnRow>          ← renders one turn (user + assistant + tool calls)
  │     │     ├── <ToolCallPanel>  ← bordered panel per tool call
  │     │     └── <Spinner>        ← shown while turn is active
  │     └── (scroll managed by Ink Box overflow)
  ├── <InputArea>              ← receives disabled bool, onSubmit callback
  ├── <StatusBar>              ← receives threadId, turnCount, usage, cwd
  └── <ApprovalModal>          ← renders as overlay when currentRequest != null
```

### `app.tsx` — orchestrator, not renderer

```tsx
// src/app.tsx
import React from "react";
import { Box, useApp } from "ink";
import { useTurns } from "./hooks/useTurns.js";
import { useApprovalQueue } from "./hooks/useApprovalQueue.js";
import { ChatView } from "./components/ChatView.js";
import { InputArea } from "./components/InputArea.js";
import { StatusBar } from "./components/StatusBar.js";
import { ApprovalModal } from "./components/ApprovalModal.js";
import type { ProtocolReader } from "./protocol/reader.js";
import type { ProtocolWriter } from "./protocol/writer.js";

type AppProps = {
  reader: ProtocolReader;
  writer: ProtocolWriter;
  onExit: () => void;
};

export function App({ reader, writer, onExit }: AppProps) {
  const { exit } = useApp();
  const { turns, threadId } = useTurns(reader);
  const { currentRequest, respond } = useApprovalQueue(reader, writer);

  const activeTurn = turns.find((t) => t.status === "active") ?? null;
  const inputDisabled = activeTurn !== null || currentRequest !== null;

  function handleSubmit(text: string) {
    writer.sendUserInput(text);
  }

  function handleInterrupt() {
    writer.sendInterrupt();
  }

  return (
    <Box flexDirection="column" height="100%">
      {currentRequest && (
        <ApprovalModal request={currentRequest} onRespond={respond} />
      )}
      <Box flexGrow={1} flexDirection="column" overflow="hidden">
        <ChatView turns={turns} />
      </Box>
      <InputArea
        disabled={inputDisabled}
        onSubmit={handleSubmit}
        onInterrupt={handleInterrupt}
      />
      <StatusBar
        threadId={threadId}
        turnCount={turns.length}
        latestUsage={turns.findLast((t) => t.usage)?.usage ?? null}
      />
    </Box>
  );
}
```

### `components/ChatView.tsx`

```tsx
import React from "react";
import { Box, Text } from "ink";
import type { TurnState } from "../hooks/useTurns.js";
import { ToolCallPanel } from "./ToolCallPanel.js";
import { Spinner } from "./Spinner.js";

type Props = { turns: TurnState[] };

const VISIBLE_TURNS = 20;

export function ChatView({ turns }: Props) {
  const visible = turns.slice(-VISIBLE_TURNS);
  return (
    <Box flexDirection="column">
      {turns.length > VISIBLE_TURNS && (
        <Text dimColor>
          ↑ {turns.length - VISIBLE_TURNS} earlier turn
          {turns.length - VISIBLE_TURNS === 1 ? "" : "s"} hidden
        </Text>
      )}
      {visible.map((turn) => (
        <TurnRow key={turn.turn_id} turn={turn} />
      ))}
    </Box>
  );
}

function TurnRow({ turn }: { turn: TurnState }) {
  const assistantText =
    [...turn.assistantLines, turn.partialLine].join("\n").trim();

  return (
    <Box flexDirection="column" marginBottom={1}>
      {/* User message */}
      <Text color="cyan">▶ {turn.userText}</Text>

      {/* Tool call panels */}
      {[...turn.toolCalls.values()].map((tc) => (
        <ToolCallPanel key={tc.item_id} toolCall={tc} />
      ))}

      {/* Assistant response */}
      {turn.status === "active" && !assistantText && <Spinner />}
      {assistantText && <Text>{assistantText}</Text>}
      {turn.status === "failed" && (
        <Text color="red">⚡ {turn.error ?? "error"}</Text>
      )}
    </Box>
  );
}
```

### `components/InputArea.tsx`

```tsx
import React, { useState } from "react";
import { Box, Text, useInput } from "ink";

type Props = {
  disabled: boolean;
  onSubmit: (text: string) => void;
  onInterrupt: () => void;
};

export function InputArea({ disabled, onSubmit, onInterrupt }: Props) {
  const [value, setValue] = useState("");

  useInput((input, key) => {
    if (disabled) {
      if (key.ctrl && input === "c") onInterrupt();
      return;
    }
    if (key.return) {
      const trimmed = value.trim();
      if (trimmed) { onSubmit(trimmed); setValue(""); }
    } else if (key.backspace || key.delete) {
      setValue((v) => v.slice(0, -1));
    } else if (key.ctrl && input === "c") {
      onInterrupt();
    } else if (!key.ctrl && !key.meta) {
      setValue((v) => v + input);
    }
  });

  return (
    <Box borderStyle="round" paddingX={1}>
      <Text color={disabled ? "gray" : "white"}>
        {disabled ? "⏳ " : "▶ "}
        {value}
        {!disabled && <Text color="cyan">█</Text>}
      </Text>
    </Box>
  );
}
```

### `components/ApprovalModal.tsx`

```tsx
import React from "react";
import { Box, Text, useInput } from "ink";
import type { ApprovalRequest, ApprovalDecision } from "../hooks/useApprovalQueue.js";

type Props = {
  request: ApprovalRequest;
  onRespond: (decision: ApprovalDecision) => void;
};

export function ApprovalModal({ request, onRespond }: Props) {
  useInput((input) => {
    const key = input.toLowerCase();
    if (key === "y") onRespond("approved");
    else if (key === "n") onRespond("denied");
    else if (key === "s") onRespond("approved_for_session");
    else if (key === "a") onRespond("abort");
  });

  return (
    <Box
      borderStyle="double"
      borderColor="yellow"
      flexDirection="column"
      paddingX={2}
      paddingY={1}
    >
      <Text bold color="yellow">⚠  Approval Required</Text>
      <Text> </Text>
      <Text>Tool: <Text bold>{request.tool}</Text></Text>
      <Text>Preview:</Text>
      <Box marginLeft={2}>
        <Text color="gray">{request.preview}</Text>
      </Box>
      <Text> </Text>
      <Text dimColor>
        [y] approve  [n] deny  [s] approve for session  [a] abort
      </Text>
    </Box>
  );
}
```

### `components/ToolCallPanel.tsx`

```tsx
import React from "react";
import { Box, Text } from "ink";
import type { ToolCallState } from "../hooks/useTurns.js";

type Props = { toolCall: ToolCallState };

export function ToolCallPanel({ toolCall }: Props) {
  const { name, arguments: args, status, content } = toolCall;

  // Truncate output to 20 lines for display
  const outputLines = (content ?? "").split("\n").slice(0, 20);
  const truncated = (content ?? "").split("\n").length > 20;

  return (
    <Box
      borderStyle="single"
      borderColor="gray"
      flexDirection="column"
      marginLeft={2}
      marginY={0}
      paddingX={1}
    >
      <Text bold color="blue">
        ─ {name} {status === "pending" ? "⏳" : status === "error" ? "✗" : "✓"}
      </Text>
      {args && <Text dimColor>$ {args}</Text>}
      {status === "done" && (
        <>
          {/* key scoped to stable item_id; positional index within a fixed panel is safe */}
          {outputLines.map((line, i) => (
            <Text key={`${toolCall.item_id}-line-${i}`} dimColor>{line}</Text>
          ))}
          {truncated && <Text dimColor>… (truncated)</Text>}
        </>
      )}
    </Box>
  );
}
```

### `components/Spinner.tsx`

```tsx
import React, { useEffect, useState } from "react";
import { Text } from "ink";

const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

export function Spinner() {
  const [frame, setFrame] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setFrame((f) => (f + 1) % FRAMES.length), 80);
    return () => clearInterval(id);
  }, []);
  return <Text color="cyan">{FRAMES[frame]} thinking…</Text>;
}
```

---

## `src/index.ts` — Entry Point

```typescript
import { spawn } from "child_process";
import { render } from "ink";
import React from "react";
import { App } from "./app.js";
import { StdioReader, StdioWriter } from "./protocol/transports/stdio.js";

function main() {
  const pythonArgs = ["-m", "pycodex", "--tui-mode"];

  const child = spawn("python3", pythonArgs, {
    stdio: ["pipe", "pipe", "inherit"],  // inherit stderr so Python errors show
    env: { ...process.env },
  });

  const reader = new StdioReader(child);
  const writer = new StdioWriter(child);

  reader.start();

  function cleanup() {
    writer.close();
    if (child.exitCode === null) {
      child.kill("SIGTERM");
    }
  }

  const { unmount } = render(
    React.createElement(App, {
      reader,
      writer,
      onExit: () => { cleanup(); process.exit(0); },
    }),
    { exitOnCtrlC: false }  // we handle Ctrl+C ourselves via useInput
  );

  child.on("exit", (code) => {
    unmount();
    process.exit(code ?? 0);
  });

  process.on("SIGINT", () => {
    writer.sendInterrupt();
    // Python will emit turn.failed then exit cleanly; child "exit" handler below drives unmount.
    // Force-kill only if Python becomes unresponsive after 5s.
    const forceKill = setTimeout(() => {
      child.kill("SIGKILL");
      process.exit(1);
    }, 5000);
    forceKill.unref(); // don't hold the event loop open
  });
}

main();
```

---

## Python Side: `core/tui_bridge.py`

```python
"""
TuiBridge: asyncio stdin reader + JSON-RPC command dispatcher for --tui-mode.

Wire protocol (Python side):
  stdin  ← JSON-RPC 2.0 commands from TypeScript (user.input, approval.response, interrupt)
  stdout → JSONL ProtocolEvents (same as --json mode, plus approval.request)

Design:
  - Single asyncio.Task reads stdin lines and dispatches commands.
  - user.input starts a new agent turn as asyncio.Task.
  - interrupt cancels the active turn task.
  - approval.request/response use asyncio.Event + result_box pattern (no threads).
  - All ProtocolEvents written to sys.stdout as JSONL; sys.stderr untouched.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from pathlib import Path

from pycodex.approval.policy import ApprovalPolicy, ApprovalStore, ReviewDecision
from pycodex.core.agent import run_turn, Session
from pycodex.core.event_adapter import EventAdapter
from pycodex.core.model_client import ModelClient
from pycodex.tools.base import ToolRegistry, ToolRouter
from pycodex.tools.orchestrator import OrchestratorConfig
from pycodex.protocol.events import ApprovalRequested


@dataclass
class TuiBridge:
    """
    Wires the TUI protocol loop to the existing pycodex runtime.

    Caller passes pre-built session, model_client, and cwd (same as __main__.py's
    _build_runtime). TuiBridge builds its own ToolRouter so it can substitute
    _tui_ask_user_fn for the blocking input() used in non-TUI modes.
    This is the only way to inject the async approval hook — run_turn does not
    accept an ask_user_fn parameter.
    """
    session: Session
    model_client: ModelClient
    cwd: Path
    approval_policy: ApprovalPolicy
    _tool_router: ToolRouter = field(init=False)
    _adapter: EventAdapter = field(init=False)
    _active_turn: asyncio.Task[None] | None = field(default=None, init=False)
    _active_turn_id: str | None = field(default=None, init=False)
    _pending_approvals: dict[str, tuple[asyncio.Event, list[ReviewDecision]]] = field(
        default_factory=dict, init=False
    )

    def __post_init__(self) -> None:
        # Build ToolRouter with TUI ask function substituted for blocking input().
        # This is the only injection point — run_turn does not accept ask_user_fn.
        orchestrator = OrchestratorConfig(
            policy=self.approval_policy,
            store=ApprovalStore(),
            ask_user_fn=self._tui_ask_user_fn,
        )
        registry = ToolRegistry(orchestrator=orchestrator)
        _register_default_tools(registry)   # same helper as __main__.py
        self._tool_router = ToolRouter(registry)
        self._adapter = EventAdapter()
        thread_event = self._adapter.start_thread()
        self._emit(thread_event)

    async def run(self) -> None:
        """Main loop: read JSON-RPC commands from stdin until EOF."""
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            try:
                line = await reader.readline()
            except asyncio.IncompleteReadError:
                break
            if not line:
                break
            await self._handle_line(line.decode().strip())

        # Wait for active turn to finish
        if self._active_turn and not self._active_turn.done():
            self._active_turn.cancel()
            try:
                await self._active_turn
            except asyncio.CancelledError:
                pass

    async def _handle_line(self, line: str) -> None:
        if not line:
            return
        try:
            import json
            cmd: dict[str, Any] = json.loads(line)
        except Exception:
            return  # ignore malformed lines

        method = cmd.get("method", "")
        params = cmd.get("params", {})

        if method == "user.input":
            await self._handle_user_input(params.get("text", ""))
        elif method == "approval.response":
            self._handle_approval_response(params)
        elif method == "interrupt":
            self._handle_interrupt()

    async def _handle_user_input(self, text: str) -> None:
        if self._active_turn and not self._active_turn.done():
            return  # drop if turn already active (shouldn't happen; TS disables input)
        self._active_turn = asyncio.create_task(self._run_turn(text))

    async def _run_turn(self, text: str) -> None:
        def on_event(agent_event: Any) -> None:
            for protocol_event in self._adapter.on_agent_event(agent_event):
                # Capture the real turn_id as soon as the adapter emits turn.started.
                # This avoids touching adapter internals and uses the protocol event
                # we're already iterating — the same event TypeScript will receive.
                if (
                    self._active_turn_id is None
                    and protocol_event.type == "turn.started"
                ):
                    self._active_turn_id = protocol_event.turn_id
                self._emit(protocol_event)

        try:
            await run_turn(
                session=self.session,
                model_client=self.model_client,
                tool_router=self._tool_router,
                cwd=self.cwd,
                user_input=text,
                on_event=on_event,
            )
        except asyncio.CancelledError:
            failed = self._adapter.turn_failed("interrupted")
            self._emit(failed)
        finally:
            self._active_turn_id = None

    async def _tui_ask_user_fn(self, tool: Any, args: dict[str, Any]) -> ReviewDecision:
        """Replace blocking input() with approval.request protocol event."""
        request_id = str(uuid4())
        event_obj: asyncio.Event = asyncio.Event()
        result_box: list[ReviewDecision] = []
        self._pending_approvals[request_id] = (event_obj, result_box)

        assert self._active_turn_id is not None, "approval requested outside active turn"
        turn_id = self._active_turn_id
        approval_event = ApprovalRequested(
            type="approval.request",
            thread_id=self._adapter.thread_id,
            turn_id=turn_id,
            request_id=request_id,
            tool=tool.name,
            preview=self._format_preview(tool, args),
        )
        self._emit(approval_event)

        await event_obj.wait()
        self._pending_approvals.pop(request_id, None)
        return result_box[0]

    def _handle_approval_response(self, params: dict[str, Any]) -> None:
        request_id = params.get("request_id", "")
        decision_str = params.get("decision", "")
        if request_id not in self._pending_approvals:
            return  # stale or unknown request_id — ignore
        decision_map = {
            "approved": ReviewDecision.APPROVED,
            "denied": ReviewDecision.DENIED,
            "approved_for_session": ReviewDecision.APPROVED_FOR_SESSION,
            "abort": ReviewDecision.ABORT,
        }
        decision = decision_map.get(decision_str)
        if decision is None:
            return
        event_obj, result_box = self._pending_approvals[request_id]
        result_box.append(decision)
        event_obj.set()

    def _handle_interrupt(self) -> None:
        if self._active_turn and not self._active_turn.done():
            self._active_turn.cancel()

    def _emit(self, event: Any) -> None:
        sys.stdout.write(event.model_dump_json() + "\n")
        sys.stdout.flush()

    @staticmethod
    def _format_preview(tool: Any, args: dict[str, Any]) -> str:
        name = getattr(tool, "name", "unknown")
        if name == "shell":
            return args.get("command", "")[:200]
        if name == "write_file":
            return args.get("file_path", "")
        return str(args)[:200]
```

> **Key design decisions**:
> 1. **Approval wiring**: `run_turn` does not accept `ask_user_fn`. The only injection point is `OrchestratorConfig` at `ToolRouter` construction. `TuiBridge.__post_init__` builds its own `ToolRouter` with `_tui_ask_user_fn` substituted for the blocking `input()` used in non-TUI modes — mirroring exactly what `_build_tool_router` does in `__main__.py`.
> 2. **Turn ID capture**: `_active_turn_id` is set when the adapter emits a `turn.started` protocol event, reading `protocol_event.turn_id` directly. This avoids touching `EventAdapter` internals and uses the same event TypeScript receives — the two sides always agree on the ID.
> 3. **`_register_default_tools`**: Import and reuse the same helper from `__main__.py`; do not duplicate the tool registration list.

---

## TypeScript Project Config

### `tui/tsconfig.json`

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "Node16",
    "moduleResolution": "Node16",
    "lib": ["ES2022"],
    "outDir": "dist",
    "rootDir": "src",
    "strict": true,
    "exactOptionalPropertyTypes": true,
    "noUncheckedIndexedAccess": true,
    "noImplicitReturns": true,
    "noFallthroughCasesInSwitch": true,
    "jsx": "react",
    "esModuleInterop": true,
    "forceConsistentCasingInFileNames": true,
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true
  },
  "include": ["src"],
  "exclude": ["src/__tests__", "node_modules", "dist"]
}
```

Strict TypeScript (`strict: true` + `exactOptionalPropertyTypes` + `noUncheckedIndexedAccess`) ensures the protocol boundary is checked at compile time.

### `tui/package.json`

```json
{
  "name": "pycodex-tui",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "main": "dist/index.js",
  "scripts": {
    "build":   "tsc",
    "dev":     "tsx src/index.ts",
    "start":   "node dist/index.js",
    "typecheck": "tsc --noEmit",
    "lint":    "eslint src --ext .ts,.tsx",
    "test":    "jest"
  },
  "dependencies": {
    "ink":          "^5.0.0",
    "react":        "^18.3.0",
    "yoga-layout":  "^3.0.0"
  },
  "devDependencies": {
    "@jest/globals":        "^29.0.0",
    "@types/react":         "^18.3.0",
    "@typescript-eslint/eslint-plugin": "^8.0.0",
    "@typescript-eslint/parser":        "^8.0.0",
    "eslint":               "^9.0.0",
    "ink-testing-library":  "^3.0.0",
    "jest":                 "^29.0.0",
    "ts-jest":              "^29.0.0",
    "tsx":                  "^4.0.0",
    "typescript":           "^5.4.0"
  }
}
```

### `tui/jest.config.ts`

```typescript
import type { Config } from "jest";

const config: Config = {
  preset: "ts-jest/presets/default-esm",
  testEnvironment: "node",
  extensionsToTreatAsEsm: [".ts", ".tsx"],
  moduleNameMapper: {
    "^(\\.{1,2}/.*)\\.js$": "$1",
  },
  transform: {
    "^.+\\.tsx?$": ["ts-jest", { useESM: true }],
  },
  testMatch: ["<rootDir>/src/__tests__/**/*.{test,spec}.{ts,tsx}"],
  collectCoverageFrom: ["src/**/*.{ts,tsx}", "!src/__tests__/**"],
};

export default config;
```

### `tui/eslint.config.js`

```javascript
// tui/eslint.config.js  (ESLint 9 flat config)
import tseslint from "@typescript-eslint/eslint-plugin";
import tsparser from "@typescript-eslint/parser";

export default [
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: { parser: tsparser },
    plugins: { "@typescript-eslint": tseslint },
    rules: {
      ...tseslint.configs.recommended.rules,
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  },
];
```

ESLint 9 uses flat config (`eslint.config.js`). The `@typescript-eslint` plugin v8 is required for ESLint 9 compatibility — v7 targets ESLint 8 and will fail to load.

---

## Files Created Across All Sub-milestones

| File | Sub-milestone | Status |
|------|---------------|--------|
| `tui/package.json` | M4A | new |
| `tui/tsconfig.json` | M4A | new |
| `tui/jest.config.ts` | M4A | new |
| `tui/eslint.config.js` | M4A | new |
| `tui/src/protocol/types.ts` | M4A | new |
| `tui/src/protocol/reader.ts` | M4A | new |
| `tui/src/protocol/writer.ts` | M4A | new |
| `tui/src/protocol/transports/stdio.ts` | M4A | new |
| `tui/src/__tests__/reader.test.ts` | M4A | new |
| `tui/src/__tests__/writer.test.ts` | M4A | new |
| `tui/src/index.ts` | M4B | new |
| `tui/src/app.tsx` | M4B | new |
| `tui/src/hooks/useProtocolEvents.ts` | M4B | new |
| `tui/src/hooks/useTurns.ts` | M4B | new |
| `tui/src/components/ChatView.tsx` | M4B | new |
| `tui/src/components/InputArea.tsx` | M4B | new |
| `tui/src/components/StatusBar.tsx` | M4B | new |
| `tui/src/components/Spinner.tsx` | M4B | new |
| `tui/src/__tests__/app.test.tsx` | M4B | new |
| `tui/src/__tests__/useTurns.test.ts` | M4B | new |
| `pycodex/core/tui_bridge.py` | M4B | new |
| `pycodex/__main__.py` | M4B | modify |
| `tests/core/test_tui_bridge.py` | M4B | new |
| `tui/src/hooks/useLineBuffer.ts` | M4C | new |
| `tui/src/__tests__/useLineBuffer.test.ts` | M4C | new |
| `pycodex/protocol/events.py` | M4C | modify (add `ItemUpdated`) |
| `pycodex/core/event_adapter.py` | M4C | modify |
| `pycodex/core/agent.py` | M4C | modify |
| `tui/src/hooks/useApprovalQueue.ts` | M4D | new |
| `tui/src/components/ApprovalModal.tsx` | M4D | new |
| `tui/src/__tests__/approvalModal.test.tsx` | M4D | new |
| `tui/src/__tests__/useApprovalQueue.test.ts` | M4D | new |
| `pycodex/protocol/events.py` | M4D | modify (add `ApprovalRequested`) |
| `tui/src/components/ToolCallPanel.tsx` | M4E | new |
| `tui/src/__tests__/toolCallPanel.test.tsx` | M4E | new |
| `tui/src/__tests__/statusBar.test.tsx` | M4E | new |
| `tui/src/__tests__/chatView.test.tsx` | M4E | new |
| `tui/src/__tests__/inputArea.test.tsx` | M4E | new |

---

## Sub-milestone M4A: Protocol Scaffold

---

### M4A — Protocol Scaffold

**Goal**: TypeScript package compiles and tests pass with no UI and no Python changes. Establishes the typed protocol boundary that all subsequent sub-milestones build on.

**Files**: `tui/package.json`, `tui/tsconfig.json`, `tui/jest.config.ts`, `tui/eslint.config.js`, `tui/src/protocol/types.ts`, `tui/src/protocol/reader.ts`, `tui/src/protocol/writer.ts`, `tui/src/protocol/transports/stdio.ts`, `tui/src/__tests__/reader.test.ts`, `tui/src/__tests__/writer.test.ts`

**Non-goals**: No UI components, no hooks, no Python changes.

#### Done criteria
- `tsc --noEmit`, `eslint src/`, `jest` all pass against just the protocol layer.
- No Python changes required; Python quality gates unchanged.

#### TypeScript tests
- `reader.test.ts`: parses valid JSONL, ignores malformed lines, emits `close` on stream end.
- `writer.test.ts`: `sendUserInput` → correct JSON-RPC line, `sendInterrupt` → correct line.

---

## Sub-milestone M4B: Python Bridge + Ink Shell

**Goal**: `node tui/dist/index.js` spawns Python, reads JSONL events, renders a working multi-turn Ink chat. Text appears after each full `turn.completed`. No streaming, no approval modal.

**Non-goals**: No streaming, no approval modal, no tool call panels, no `item.updated` or `approval.request` events. Full scroll navigation is M5 polish — M4 renders the most recent 20 turns with a hidden-count indicator.

#### Done criteria
- `node tui/dist/index.js` launches Ink app; multi-turn chat works end to end.
- `python -m pycodex "…"` and `python -m pycodex --json "…"` unchanged.
- `mypy --strict pycodex/`, `ruff check`, `ruff format`, `pytest tests/ -v` all pass.
- `tsc --noEmit`, `eslint src/`, `jest` all pass.

**Test it**: `node tui/dist/index.js` → type "what is 2+2" → see response after `turn.completed`.

#### Python tests (`tests/core/test_tui_bridge.py`)
- `test_user_input_command_starts_turn` — `user.input` → `run_turn` invoked.
- `test_interrupt_cancels_active_turn` — `interrupt` while turn running → task cancelled.
- `test_jsonl_emitted_for_each_event` — agent events → valid JSON lines on stdout.
- `test_unknown_command_ignored` — unrecognized method → no crash.
- `test_thread_started_emitted_on_init` — `thread.started` line on bridge construction.

#### TypeScript tests

Priority is hook/state correctness first, one integration smoke test second. Component-specific tests (ChatView, InputArea, StatusBar rendering) are deferred to M4E when behavior has stabilized.

- `useTurns.test.ts`: `turn.started` appends turn; `turn.completed` fills `final_text` and marks status `"completed"`; `turn.failed` sets `status: "failed"` and `error`; unknown event type → no state mutation (default branch).
- `app.test.tsx` (ink-testing-library, 1 test): end-to-end smoke — simulate `turn.started` + `turn.completed` events → response text visible in output; input is disabled while a turn is active.

---

## Sub-milestone M4C: Streaming Text (`item.updated`)

**Goal**: Model response text appears line-by-line as the model generates it.

**Non-goals**: No approval modal, no tool call panels, no smooth animation tick (Codex-style adaptive streaming). Frame-gating via `setImmediate` prevents CPU spin at high token rates but is not a visual polish feature.

### Protocol changes
- Python `protocol/events.py`: add `ItemUpdated` (`type="item.updated"`, `delta: str`).
- Python `core/agent.py`: surface `OutputTextDelta` through `_emit()` as `AgentEvent`.
- Python `core/event_adapter.py`: map `TextDelta` → `ItemUpdated(item_id=active_item_id, delta=delta)`.
- TypeScript `protocol/types.ts`: add `item.updated` variant.

### `useLineBuffer` hook

```typescript
// tui/src/hooks/useLineBuffer.ts
import { useReducer } from "react";

type LineBufferState = { committed: string[]; partial: string };
type LineBufferAction =
  | { type: "push"; delta: string }
  | { type: "flush" }
  | { type: "reset" };

function lineBufferReducer(
  state: LineBufferState,
  action: LineBufferAction,
): LineBufferState {
  switch (action.type) {
    case "push": {
      const raw = state.partial + action.delta;
      const lines = raw.split("\n");
      const partial = lines.pop() ?? "";
      // Preserve intentional blank lines from model output.
      return { committed: [...state.committed, ...lines], partial };
    }
    case "flush":
      return {
        // Drop only trailing empty partial at turn end (avoid phantom final blank line).
        committed: [...state.committed, state.partial].filter(Boolean),
        partial: "",
      };
    case "reset":
      return { committed: [], partial: "" };
    default: {
      const _exhaustive: never = action;
      return state;
    }
  }
}

export function useLineBuffer() {
  return useReducer(lineBufferReducer, { committed: [], partial: "" });
}
```

`useTurns` dispatches `push` / `flush` / `reset` actions; `committed` and `partial` are reactive state — no imperative method calls.

### Frame-gating for high token rates

At high generation rates, `item.updated` events can arrive faster than Ink re-renders. Batch deltas within a single event-loop tick using `setImmediate` to avoid CPU spin:

```typescript
// In useTurns.ts — applied per active turn
const pendingDelta = useRef<string>("");
const flushScheduled = useRef(false);

function scheduleDeltaFlush(turnId: string) {
  if (flushScheduled.current) return;
  flushScheduled.current = true;
  setImmediate(() => {
    if (pendingDelta.current) {
      dispatch({ type: "item.updated", turn_id: turnId, delta: pendingDelta.current });
      pendingDelta.current = "";
    }
    flushScheduled.current = false;
  });
}

// On each item.updated event from the reader:
pendingDelta.current += event.delta;
scheduleDeltaFlush(event.turn_id);
```

This is not a smooth animation tick — it is a correctness guard. The non-goal remains: no Codex-style adaptive streaming tick.

### Done criteria
- Streaming text appears line-by-line.
- `item.updated` in `--json` standalone mode (existing JSONL consumers see it).
- All M4A and M4B tests still pass.

**Test it**: `node tui/dist/index.js` → prompt producing long answer → lines appear progressively.

### Tests
- `useLineBuffer.test.ts`: `push` commits on `\n` and holds partial; `flush` moves partial into committed; `reset` clears all; exhaustive action switch enforced by TypeScript `never` check.
- `useTurns.test.ts` extend: `item.updated` deltas accumulate in `partialLine`; committed on `\n`.
- Python `test_event_adapter.py` extend: `test_text_delta_emits_item_updated`, `test_multiple_deltas_same_item_id`, `test_item_id_cleared_between_turns`.

---

## Sub-milestone M4D: Approval Modal

**Goal**: Mutating tool calls emit `approval.request` from Python. TypeScript shows `ApprovalModal`. User presses key, TypeScript sends `approval.response`, Python unblocks.

**Non-goals**: No diff display, no keyboard shortcut customization.

### Done criteria
- Mutating tool calls prompt via `ApprovalModal`, not `input()`.
- Multiple approvals queue; resolved in order.
- ABORT stops active turn; `APPROVED_FOR_SESSION` caching still works.
- Quality gates pass.

**Test it**: `node tui/dist/index.js` → "create hello.txt" → approval modal → press `y` → file created.

### Tests
- `useApprovalQueue.test.ts`: `approval.request` enqueues; `respond()` calls writer + dequeues.
- `approvalModal.test.tsx`: `y/n/s/a` keys → correct `ApprovalDecision` callbacks.
- `app.test.tsx` extend: modal shows when `currentRequest != null`; input disabled during approval.
- Python `test_tui_bridge.py` extend: `tui_ask_user_fn` emits `approval.request`; matching `approval.response` unblocks it with correct `ReviewDecision`; unknown `request_id` ignored.

---

## Sub-milestone M4E: Tool Call Panels + Status + Interrupt

**Goal**: Tool calls render as inline bordered panels. Status bar shows token usage. Ctrl+C sends `interrupt` command to Python cleanly.

**Non-goals**: No syntax-highlighted diffs, no collapsible panels, no MCP tool display.

### Done criteria
- Tool calls visible as panels with command + truncated output.
- Status bar shows `↑ input  ↓ output` token counts after each turn.
- Ctrl+C sends `interrupt` → Python cancels turn → Ink shows "⚡ interrupted".
- All prior sub-milestone tests still pass.

**Test it**: `node tui/dist/index.js` → "list python files and read pyproject.toml" → shell + read_file panels populate in real time.

### Tests

Component tests for ChatView, InputArea, and StatusBar land here once behavior has stabilized across M4A-D. This avoids rewriting tests as protocol and hook contracts evolve.

- `toolCallPanel.test.tsx`: `item.started` inserts placeholder; `item.completed` fills result; two calls → two distinct panels keyed by `item_id`.
- `statusBar.test.tsx`: `turn.completed` with `usage` → `↑ input ↓ output` token counts visible; cumulative across turns.
- `chatView.test.tsx`: renders last 20 turns; hidden-count indicator appears above turn 21+; `turn.failed` with `error="interrupted"` renders `⚡` not a red error.
- `inputArea.test.tsx`: text entry, submit clears input, Ctrl+C fires `onInterrupt`, input is visually disabled when `disabled=true`.
- `app.test.tsx` extend: Ctrl+C → `sendInterrupt()` called; `turn.failed(error="interrupted")` → "⚡ interrupted" rendered.
- Python `test_tui_bridge.py` extend: `interrupt` → active task cancelled.

---

## Protocol Contract Clarity

These behaviors must be explicit and consistent across Python and TypeScript.

### Interrupt semantics

- `interrupt` command → Python cancels active `asyncio.Task` via `_active_turn.cancel()`.
- Cancelled task catches `asyncio.CancelledError` → emits `turn.failed` with `error="interrupted"`.
- TypeScript `TurnRow` renders `turn.failed` with `error="interrupted"` as `⚡ interrupted` (not an error state — a user-driven stop).
- If no turn is active when `interrupt` arrives, it is silently ignored.
- `turn.completed` is never emitted for an interrupted turn.

### `--tui-mode` parser flag

- `--tui-mode` is a boolean flag with no positional prompt argument. It must not conflict with the existing `PROMPT` positional used by the default and `--json` modes.
- In `__main__.py`, wire as a mutually exclusive group or a simple `add_argument("--tui-mode", action="store_true")` that routes to `TuiBridge.run()` instead of `_run_prompt()` / `_run_prompt_json()`.
- When `--tui-mode` is active, the positional `PROMPT` argument must be declared optional (or excluded) to avoid argparse errors when no prompt is provided on the command line.

### Unknown event / command fallback

**Python side** (`tui_bridge.py`): Unknown `method` values in JSON-RPC commands are silently ignored — `_handle_line` falls through all `if/elif` branches with no action.

**TypeScript side** (`StdioReader`): Unknown `type` values in inbound JSONL events are passed to all `onEvent` handlers as-is (typed as `ProtocolEvent`). Hooks that switch on `event.type` must include a `default` no-op branch so unknown events cause no state mutation. Example:

```typescript
// In useTurns reducer:
default:
  return state; // unknown event type — ignore safely
```

### `turn_failed` vs `turn.completed` on abort

When approval decision is `"abort"`:
- Python resolves `_tui_ask_user_fn` with `ReviewDecision.ABORT`.
- The orchestrator raises `ToolAborted`.
- `run_turn` catches `ToolAborted`, emits `TurnCompleted(final_text=\"Aborted by user.\")`, and returns.
- Adapter maps that to protocol `turn.completed` (not `turn.failed`) to preserve the existing M3 contract.

`turn.failed(error=\"interrupted\")` remains reserved for explicit cancellation/interruption paths (for example Ctrl+C / `interrupt` command), not approval abort.

---

## Codex Reference Map

| PyCodex component | Codex equivalent | Key simplification |
|---|---|---|
| `tui/src/index.ts` spawns Python | TypeScript spawns Rust binary | Same pattern; Python vs Rust |
| `StdioReader`/`StdioWriter` | Codex exec event stream over stdio | Same readline approach |
| `ProtocolReader`/`ProtocolWriter` interfaces | n/a (Codex doesn't abstract transport yet) | Enables M6 WebSocket swap with zero UI changes |
| `useLineBuffer` in `useTurns` | `MarkdownStreamCollector` + `StreamController` | No animation tick; newline-gate only |
| `useApprovalQueue` + `ApprovalModal` | `ApprovalOverlay` + `advance_queue()` | Same queue model; no MCP elicitation type |
| `asyncio.Event` in `tui_bridge.py` | mpsc send/recv across Rust threads | Asyncio-native, no thread boundary |
| `ToolCallPanel` keyed by `item_id` | `ChatWidget.active_cell` mutation | Simpler: Map lookup, no cell coalescing |
| `StatusBar` token display | `format_tokens_compact()` | Same info, simpler component |
| Ctrl+C → `interrupt` JSON-RPC command | OS signal to Rust process | Command over pipe vs signal |
| JSON-RPC envelope over stdio | Codex exec protocol | Same 2.0 framing; transport-agnostic |

## What Codex Has That PyCodex Intentionally Skips

- Adaptive streaming tick (smooth vs catch-up) — `useLineBuffer` commit-on-newline is enough
- MCP elicitation approval type — M5+ scope
- External editor (`$EDITOR`) — polish
- Transcript overlay (Ctrl+T) — polish
- Multi-agent thread picker — out of scope
- Session resume picker — M6
- Rate limit display — M6

---

## Quality Gates (all sub-milestones)

**Python**:
```
ruff check . --fix
ruff format .
mypy --strict pycodex/
pytest tests/ -v
```

**TypeScript**:
```
cd tui
tsc --noEmit
eslint src/
jest --coverage
```

Both must be clean before any sub-milestone is marked done.

**Root-level composite gate** (cross-boundary changes):

```makefile
# Makefile (root) — run both sides in one command
.PHONY: check check-py check-ts

check: check-py check-ts

check-py:
	ruff check . --fix
	ruff format .
	mypy --strict pycodex/
	pytest tests/ -v

check-ts:
	cd tui && npm run typecheck && npm run lint && npm test -- --coverage
```

Run `make check` before marking any cross-boundary sub-milestone complete. CI calls this target once.

---

## Dependency Notes

**Python**: zero new runtime deps. `tui_bridge.py` uses only `asyncio`, `sys`, `uuid`, and existing `pycodex` modules.

**TypeScript** (`tui/package.json`):

| Package | Role |
|---|---|
| `react ^18` | Component model |
| `ink ^5` | Terminal renderer (wraps Yoga + React) |
| `yoga-layout ^3` | Flexbox layout engine (peer dep of Ink) |
| `typescript ^5` | Strict type checking |
| `ink-testing-library ^3` | Component unit tests without real TTY |
| `ts-jest ^29` | Jest TypeScript transformer |
| `tsx ^4` | Dev-time `ts-node` alternative (faster) |
| `eslint + @typescript-eslint ^8` | Linting |

### TypeScript Toolchain Known Issues

**ESM + ts-jest + Ink**: Ink and ink-testing-library ship as ESM-only packages. ts-jest excludes `node_modules` from transformation by default, causing `SyntaxError: Cannot use import statement` at test time. Add to `jest.config.ts`:

```typescript
transformIgnorePatterns: ["node_modules/(?!(ink|ink-testing-library)/)"],
```

Pin exact versions in `package-lock.json` and validate with `npm ci` before starting M4A. If `jest` fails with import errors after an `npm update`, check whether `ink` or `ink-testing-library` changed their ESM export map — the `transformIgnorePatterns` list may need updating.

---

## Multi-Client Extensibility (M6 and Beyond)

The `ProtocolReader` / `ProtocolWriter` abstraction is the extension point for future clients.

```
M4  Ink TUI         → StdioReader   / StdioWriter   (stdio pipe)
M6  Ink TUI         → WsReader      / WsWriter       (WebSocket, same Ink UI)
M6  VS Code ext     → WsReader      / WsWriter       (webview, same protocol)
M6  Web frontend    → SseReader     / FetchWriter     (browser EventSource + POST)
M6+ Remote client   → WsReader      / WsWriter       (remote WebSocket over SSH)
```

All of these share:
- `protocol/types.ts` — identical event and command shapes
- `hooks/useTurns.ts`, `hooks/useApprovalQueue.ts` — identical state logic
- Python `tui_bridge.py` / `core/server.py` — identical command dispatch

Only the transport concrete class changes. No protocol changes. No hook changes. No Python agent changes.
