"""Adapter from internal agent lifecycle events to protocol events."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from uuid import uuid4

from pycodex.core.agent import (
    AgentEvent,
    TextDeltaReceived,
    ToolCallDispatched,
    ToolResultReceived,
    TurnCompleted,
)
from pycodex.core.agent import TurnStarted as AgentTurnStarted
from pycodex.protocol.events import (
    ItemCompleted,
    ItemStarted,
    ItemUpdated,
    ProtocolEvent,
    ThreadStarted,
    TokenUsage,
    TurnFailed,
    TurnStarted,
)
from pycodex.protocol.events import TurnCompleted as ProtocolTurnCompleted


@dataclass(slots=True)
class EventAdapter:
    """Stateful per-run adapter for protocol lifecycle events."""

    thread_id: str = field(default_factory=lambda: str(uuid4()))
    _turn_counter: int = 0
    _item_counter: int = 0
    _inflight: dict[str, str] = field(default_factory=dict)
    _current_turn_id: str | None = None
    _assistant_item_id: str | None = None
    _thread_started: bool = False

    def start_thread(self) -> ThreadStarted:
        """Build the canonical thread-start event for this adapter instance."""
        if self._thread_started:
            raise RuntimeError("thread.started has already been emitted for this adapter")
        self._thread_started = True
        return ThreadStarted(thread_id=self.thread_id)

    def on_agent_event(self, event: AgentEvent) -> list[ProtocolEvent]:
        """Map one internal agent event to ordered protocol events."""
        if isinstance(event, AgentTurnStarted):
            self._turn_counter += 1
            self._current_turn_id = f"turn_{self._turn_counter}"
            self._assistant_item_id = None
            return [
                TurnStarted(
                    thread_id=self.thread_id,
                    turn_id=self._current_turn_id,
                )
            ]

        if isinstance(event, TextDeltaReceived):
            turn_id = self._require_active_turn_id()
            item_id = self._resolve_assistant_item_id(
                turn_id=turn_id,
                suggested_item_id=event.item_id,
            )
            return [
                ItemUpdated(
                    thread_id=self.thread_id,
                    turn_id=turn_id,
                    item_id=item_id,
                    delta=event.delta,
                )
            ]

        if isinstance(event, ToolCallDispatched):
            turn_id = self._require_active_turn_id()
            call_id = event.call_id.strip()
            item_id = call_id or self._next_item_id(turn_id)
            self._inflight[call_id] = item_id
            arguments = (
                event.arguments
                if isinstance(event.arguments, str)
                else json.dumps(event.arguments, sort_keys=True, ensure_ascii=True)
            )
            return [
                ItemStarted(
                    thread_id=self.thread_id,
                    turn_id=turn_id,
                    item_id=item_id,
                    item_kind="tool_call",
                    name=event.name,
                    arguments=arguments,
                )
            ]

        if isinstance(event, ToolResultReceived):
            turn_id = self._require_active_turn_id()
            call_id = event.call_id.strip()
            item_id = self._inflight.pop(call_id, call_id or self._next_item_id(turn_id))
            return [
                ItemCompleted(
                    thread_id=self.thread_id,
                    turn_id=turn_id,
                    item_id=item_id,
                    item_kind="tool_result",
                    content=event.result,
                )
            ]

        if isinstance(event, TurnCompleted):
            turn_id = self._require_active_turn_id()
            usage = _to_token_usage(event.usage)
            self._current_turn_id = None
            self._assistant_item_id = None
            return [
                ProtocolTurnCompleted(
                    thread_id=self.thread_id,
                    turn_id=turn_id,
                    final_text=event.final_text,
                    usage=usage,
                )
            ]

        return []

    def failure_turn_id(self) -> str:
        """Return turn ID to use when emitting a turn-level failure event."""
        if self._current_turn_id is not None:
            return self._current_turn_id
        return f"turn_{self._turn_counter + 1}"

    def turn_failed(self, error: Exception | str) -> TurnFailed:
        """Build a turn.failed event using adapter-owned thread/turn identity."""
        if isinstance(error, Exception):
            message = str(error).strip() or type(error).__name__
        else:
            message = str(error).strip()
        return TurnFailed(
            thread_id=self.thread_id,
            turn_id=self.failure_turn_id(),
            error=message,
        )

    def _next_item_id(self, turn_id: str) -> str:
        self._item_counter += 1
        return f"item_{turn_id}_{self._item_counter}"

    def _require_active_turn_id(self) -> str:
        if self._current_turn_id is None:
            raise RuntimeError("received non-start event without active turn")
        return self._current_turn_id

    def _resolve_assistant_item_id(self, *, turn_id: str, suggested_item_id: str | None) -> str:
        normalized = suggested_item_id.strip() if isinstance(suggested_item_id, str) else ""
        if normalized:
            self._assistant_item_id = normalized
            return normalized

        if self._assistant_item_id is None:
            self._assistant_item_id = self._next_item_id(turn_id)
        return self._assistant_item_id


def _to_token_usage(raw_usage: dict[str, int] | None) -> TokenUsage | None:
    if raw_usage is None:
        return None

    input_tokens = raw_usage.get("input_tokens")
    output_tokens = raw_usage.get("output_tokens")
    if (
        not isinstance(input_tokens, int)
        or isinstance(input_tokens, bool)
        or not isinstance(output_tokens, int)
        or isinstance(output_tokens, bool)
    ):
        return None

    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
