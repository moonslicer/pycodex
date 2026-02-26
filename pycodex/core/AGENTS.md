# pycodex/core — Module Rules

Applies in addition to root `AGENTS.md`. Root rules take precedence when they conflict.

## Agent Loop
- The agent loop in `agent.py` must be purely async end-to-end — no blocking calls anywhere in the call stack.
- Termination condition: loop exits when the model returns a response with no tool calls.
- Concurrent tool dispatch: read-only tool calls may run via `asyncio.gather()`; mutating calls to the same resource must be sequential.
- Do not add retry logic to the agent loop itself — retries belong in `model_client.py` and `tools/orchestrator.py`.

## Session
- `session.py` is the **single source of truth** for message history.
- Never mutate the history list outside of `Session` methods (`append_user_message`, `append_tool_result`).
- `to_prompt()` must return a new list — never expose the internal list directly.

## Model Client
- `model_client.py` must handle streaming errors: reconnect once on transient failure, then surface the error.
- All streaming events must be yielded as typed dataclasses — never yield raw dicts.
- Do not log or print inside `model_client.py`; emit events via callback or return them.

## Events
- All events are emitted via a callback passed into the agent at construction — never printed directly.
- Events must be emitted at each lifecycle point: turn started, tool call dispatched, tool result received, turn completed.
