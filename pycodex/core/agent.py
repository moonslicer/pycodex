"""Async agent loop orchestration for model sampling and tool execution."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from inspect import isawaitable
from pathlib import Path
from typing import Any, Literal, Protocol

from pycodex.core.model_client import OutputItemDone, OutputTextDelta
from pycodex.core.session import PromptItem, Session
from pycodex.tools.orchestrator import ToolAborted

_log = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class TurnStarted:
    """Event emitted when an agent turn begins."""

    user_input: str
    type: Literal["turn_started"] = "turn_started"


@dataclass(slots=True, frozen=True)
class ToolCallDispatched:
    """Event emitted before a tool call is executed."""

    call_id: str
    name: str
    arguments: str | dict[str, Any]
    type: Literal["tool_call_dispatched"] = "tool_call_dispatched"


@dataclass(slots=True, frozen=True)
class ToolResultReceived:
    """Event emitted after a tool call result is received."""

    call_id: str
    name: str
    result: str
    type: Literal["tool_result_received"] = "tool_result_received"


@dataclass(slots=True, frozen=True)
class TurnCompleted:
    """Event emitted when the turn completes with final text."""

    final_text: str
    type: Literal["turn_completed"] = "turn_completed"


AgentEvent = TurnStarted | ToolCallDispatched | ToolResultReceived | TurnCompleted
EventCallback = Callable[[AgentEvent], None | Awaitable[None]]


class SupportsModelClient(Protocol):
    """Protocol for model clients that can stream response events."""

    def stream(
        self,
        messages: list[PromptItem],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[Any]:
        """Yield streaming model events."""


class SupportsToolRouter(Protocol):
    """Protocol for routing tool calls from model output."""

    def tool_specs(self) -> list[dict[str, Any]]:
        """Return tool specs for model input."""

    async def dispatch(
        self,
        *,
        name: str,
        arguments: str | dict[str, Any],
        cwd: Path,
    ) -> str:
        """Dispatch a tool call to a registered handler."""


@dataclass(slots=True, frozen=True)
class ParsedToolCall:
    """Normalized function-call item extracted from model output."""

    call_id: str
    name: str
    arguments: str | dict[str, Any]


@dataclass(slots=True)
class Agent:
    """Coordinates the model <-> tools loop for a single user turn."""

    session: Session
    model_client: SupportsModelClient
    tool_router: SupportsToolRouter
    cwd: Path
    on_event: EventCallback | None = None

    async def run_turn(self, user_input: str) -> str:
        """Run one user turn until the model emits no tool calls."""
        _log.debug("turn started: %r", user_input[:80])
        self.session.append_user_message(user_input)
        await self._emit(TurnStarted(user_input=user_input))

        while True:
            tool_calls, text = await self._sample_model_once()
            if not tool_calls:
                _log.info("turn completed: %d chars", len(text))
                await self._emit(TurnCompleted(final_text=text))
                return text

            if text:
                self.session.append_assistant_message(text)

            for tool_call in tool_calls:
                self.session.append_function_call(
                    call_id=tool_call.call_id,
                    name=tool_call.name,
                    arguments=tool_call.arguments,
                )
                _log.debug(
                    "dispatching tool %r (call_id=%s) args=%s",
                    tool_call.name,
                    tool_call.call_id,
                    _summarize_args(tool_call.arguments),
                )
                await self._emit(
                    ToolCallDispatched(
                        call_id=tool_call.call_id,
                        name=tool_call.name,
                        arguments=tool_call.arguments,
                    )
                )
                try:
                    result = await self.tool_router.dispatch(
                        name=tool_call.name,
                        arguments=tool_call.arguments,
                        cwd=self.cwd,
                    )
                except ToolAborted:
                    # ABORT is terminal for this turn: return immediately
                    # without dispatching additional tool calls.
                    abort_text = "Aborted by user."
                    _log.info("turn aborted by user during tool %r", tool_call.name)
                    await self._emit(TurnCompleted(final_text=abort_text))
                    return abort_text
                _log.debug("tool %r result: %d chars", tool_call.name, len(result))
                self.session.append_tool_result(tool_call.call_id, result)
                await self._emit(
                    ToolResultReceived(
                        call_id=tool_call.call_id,
                        name=tool_call.name,
                        result=result,
                    )
                )

    async def _sample_model_once(self) -> tuple[list[ParsedToolCall], str]:
        text_parts: list[str] = []
        tool_calls: list[ParsedToolCall] = []

        async for event in self.model_client.stream(
            messages=self.session.to_prompt(),
            tools=self.tool_router.tool_specs(),
        ):
            if isinstance(event, OutputTextDelta):
                text_parts.append(event.delta)
            elif isinstance(event, OutputItemDone):
                parsed = _parse_tool_call_item(item=event.item, ordinal=len(tool_calls) + 1)
                if parsed is not None:
                    tool_calls.append(parsed)
                elif not text_parts:
                    completed_text = _extract_assistant_text_from_item(event.item)
                    if completed_text is not None:
                        text_parts.append(completed_text)

        return tool_calls, "".join(text_parts)

    async def _emit(self, event: AgentEvent) -> None:
        if self.on_event is None:
            return
        maybe_awaitable = self.on_event(event)
        if isawaitable(maybe_awaitable):
            await maybe_awaitable


async def run_turn(
    *,
    session: Session,
    model_client: SupportsModelClient,
    tool_router: SupportsToolRouter,
    cwd: Path,
    user_input: str,
    on_event: EventCallback | None = None,
) -> str:
    """Run one agent turn with explicit dependencies."""
    agent = Agent(
        session=session,
        model_client=model_client,
        tool_router=tool_router,
        cwd=cwd,
        on_event=on_event,
    )
    return await agent.run_turn(user_input)


def _parse_tool_call_item(item: Any, *, ordinal: int) -> ParsedToolCall | None:
    if not isinstance(item, dict):
        return None

    if item.get("type") != "function_call":
        return None

    name = item.get("name")
    if not isinstance(name, str) or not name:
        return None

    arguments = item.get("arguments", "{}")
    if isinstance(arguments, dict):
        normalized_arguments: str | dict[str, Any] = arguments
    elif isinstance(arguments, str):
        normalized_arguments = arguments
    else:
        normalized_arguments = "{}"

    call_id_raw = item.get("call_id", item.get("id"))
    call_id = call_id_raw if isinstance(call_id_raw, str) and call_id_raw else f"call_{ordinal}"

    return ParsedToolCall(
        call_id=call_id,
        name=name,
        arguments=normalized_arguments,
    )


def _extract_assistant_text_from_item(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None
    if item.get("type") != "message":
        return None
    if item.get("role") != "assistant":
        return None

    content = item.get("content")
    if not isinstance(content, list):
        return None

    text_parts: list[str] = []
    for content_item in content:
        if not isinstance(content_item, dict):
            continue
        if content_item.get("type") != "output_text":
            continue

        text = content_item.get("text")
        if isinstance(text, str):
            text_parts.append(text)

    if not text_parts:
        return None
    return "".join(text_parts)


_SUMMARIZE_TRUNCATE = 120  # chars per value before truncating


def _summarize_args(arguments: str | dict[str, Any]) -> str:
    """Return a compact one-line summary of tool arguments for debug logging.

    Long string values are truncated so a write_file call with thousands of
    characters of content doesn't flood the log.
    """
    if isinstance(arguments, str):
        raw = arguments.strip()
        return raw[:_SUMMARIZE_TRUNCATE] + ("…" if len(raw) > _SUMMARIZE_TRUNCATE else "")

    parts: list[str] = []
    for k, v in arguments.items():
        v_str = repr(v)
        if len(v_str) > _SUMMARIZE_TRUNCATE:
            v_str = v_str[:_SUMMARIZE_TRUNCATE] + "…'"
        parts.append(f"{k}={v_str}")
    return "{" + ", ".join(parts) + "}"
