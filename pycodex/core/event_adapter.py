"""Adapter from internal agent lifecycle events to protocol events."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from uuid import uuid4

from pycodex.core.agent import AgentEvent, ToolCallDispatched, ToolResultReceived, TurnCompleted
from pycodex.core.agent import TurnStarted as AgentTurnStarted
from pycodex.protocol.events import ItemCompleted, ItemStarted, ProtocolEvent, TurnStarted
from pycodex.protocol.events import TurnCompleted as ProtocolTurnCompleted


@dataclass(slots=True)
class EventAdapter:
    """Stateful per-run adapter for protocol lifecycle events."""

    thread_id: str = field(default_factory=lambda: str(uuid4()))
    _turn_counter: int = 0
    _item_counter: int = 0
    _inflight: dict[str, str] = field(default_factory=dict)
    _current_turn_id: str | None = None

    def on_agent_event(self, event: AgentEvent) -> list[ProtocolEvent]:
        """Map one internal agent event to ordered protocol events."""
        if isinstance(event, AgentTurnStarted):
            self._turn_counter += 1
            self._current_turn_id = f"turn_{self._turn_counter}"
            return [
                TurnStarted(
                    thread_id=self.thread_id,
                    turn_id=self._current_turn_id,
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
            return [
                ProtocolTurnCompleted(
                    thread_id=self.thread_id,
                    turn_id=turn_id,
                    final_text=event.final_text,
                    usage=None,
                )
            ]

        return []

    def _next_item_id(self, turn_id: str) -> str:
        self._item_counter += 1
        return f"item_{turn_id}_{self._item_counter}"

    def _require_active_turn_id(self) -> str:
        if self._current_turn_id is None:
            raise RuntimeError("received non-start event without active turn")
        return self._current_turn_id
