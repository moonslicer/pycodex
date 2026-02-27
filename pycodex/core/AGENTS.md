# pycodex/core — Module Rules

Applies in addition to root `AGENTS.md`. Root rules take precedence when they conflict.

## Agent Loop
- The agent loop in `agent.py` must be purely async end-to-end — no blocking calls anywhere in the call stack.
- Termination condition: loop exits when the model returns a response with no tool calls.
- Current dispatch behavior is sequential in model-emitted order; do not introduce parallel tool dispatch without an explicit contract change and deterministic regression tests.
- Do not add retry logic to the agent loop itself — retries belong in `model_client.py` and `tools/orchestrator.py`.
- `ToolAborted` is terminal for the active turn and must result in immediate turn completion.

## Session
- `session.py` is the **single source of truth** for message history.
- Never mutate the history list outside of `Session` methods (`append_user_message`, `append_assistant_message`, `append_function_call`, `append_tool_result`).
- `to_prompt()` must return a new list — never expose the internal list directly.

## Model Client
- `model_client.py` must handle streaming errors: reconnect once on transient failure, then surface the error.
- All streaming events must be yielded as typed dataclasses — never yield raw dicts.
- Do not log or print inside `model_client.py`; emit events via callback or return them.

## Events
- All events are emitted via a callback passed into the agent at construction — never printed directly.
- Events must be emitted at each lifecycle point: turn started, tool call dispatched, tool result received, turn completed.
- Event assertions should validate event type/order and structured fields, not prose wording.

## Logging
- Use `logging.getLogger(__name__)` for module-level loggers in `agent.py` and adjacent modules.
- Log level semantics: DEBUG for internal state (event types, dispatch routing), INFO for lifecycle milestones (turn start/end), WARNING/ERROR for unexpected states.
- Never configure logging (`basicConfig`, `addHandler`) inside library modules — configuration belongs in `__main__.py` only.
- The prohibition on logging in `model_client.py` stands: use the event callback instead.
