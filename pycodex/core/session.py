"""Session state and prompt history management for agent turns."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from pycodex.core.config import Config

MAX_TOOL_RESULT_CHARS = 200_000
_MISSING_TOOL_OUTPUT_PLACEHOLDER = "aborted"


class UserMessageItem(TypedDict):
    """Prompt item emitted when a user sends input."""

    role: Literal["user"]
    content: str


class AssistantMessageItem(TypedDict):
    """Prompt item emitted when the assistant returns plain text."""

    role: Literal["assistant"]
    content: str


class SystemMessageItem(TypedDict):
    """Prompt item emitted for system/developer instructions."""

    role: Literal["system"]
    content: str


class ToolResultMessageItem(TypedDict):
    """Prompt item emitted after tool execution completes."""

    role: Literal["tool"]
    tool_call_id: str
    content: str


class FunctionCallItem(TypedDict):
    """Prompt item emitted when the model requests a function call."""

    type: Literal["function_call"]
    call_id: str
    name: str
    arguments: str


PromptItem = (
    UserMessageItem
    | AssistantMessageItem
    | SystemMessageItem
    | ToolResultMessageItem
    | FunctionCallItem
)


@dataclass(slots=True)
class Session:
    """Container for conversation history used to build model prompts."""

    config: Config | None = None
    _history: list[PromptItem] = field(default_factory=list)
    _initial_context_injected: bool = False

    def append_user_message(self, text: str) -> None:
        """Append a user message to the conversation history."""
        self._history.append({"role": "user", "content": text})

    def append_system_message(self, text: str) -> None:
        """Append a system context message to the conversation history."""
        self._history.append({"role": "system", "content": text})

    def append_assistant_message(self, text: str) -> None:
        """Append an assistant message to the conversation history."""
        self._history.append({"role": "assistant", "content": text})

    def append_tool_result(self, call_id: str, result: str) -> None:
        """Append a tool result to the conversation history."""
        content = result
        if len(content) > MAX_TOOL_RESULT_CHARS:
            content = f"{content[:MAX_TOOL_RESULT_CHARS]}\n...[truncated by session history cap]"
        self._history.append({"role": "tool", "tool_call_id": call_id, "content": content})

    def append_function_call(
        self,
        *,
        call_id: str,
        name: str,
        arguments: str | dict[str, Any],
    ) -> None:
        """Append a model function-call item to the conversation history."""
        normalized_arguments: str
        if isinstance(arguments, str):
            normalized_arguments = arguments
        elif isinstance(arguments, dict):
            normalized_arguments = json.dumps(arguments, ensure_ascii=True)
        else:  # pragma: no cover - defensive boundary
            normalized_arguments = "{}"

        self._history.append(
            {
                "type": "function_call",
                "call_id": call_id,
                "name": name,
                "arguments": normalized_arguments,
            }
        )

    def prepend_items(self, items: list[PromptItem]) -> None:
        """Prepend prompt items before existing session history."""
        self._history = list(items) + self._history

    def has_initial_context(self) -> bool:
        """Return whether initial context has already been injected."""
        return self._initial_context_injected

    def mark_initial_context_injected(self) -> None:
        """Mark initial context as injected for this session."""
        self._initial_context_injected = True

    def to_prompt(self) -> list[PromptItem]:
        """Return a detached copy of history for model input payloads."""
        prompt = [item.copy() for item in self._history]
        return _normalize_prompt_history(prompt)


def _normalize_prompt_history(history: list[PromptItem]) -> list[PromptItem]:
    pending_function_calls: dict[str, deque[int]] = {}

    for index, item in enumerate(history):
        item_type = item.get("type")
        if item_type == "function_call":
            call_id = item.get("call_id")
            if isinstance(call_id, str) and call_id:
                pending_function_calls.setdefault(call_id, deque()).append(index)
            continue

        role = item.get("role")
        if role != "tool":
            continue

        call_id = item.get("tool_call_id")
        if not isinstance(call_id, str) or not call_id:
            continue
        pending_indices = pending_function_calls.get(call_id)
        if pending_indices is None or len(pending_indices) == 0:
            continue
        pending_indices.popleft()
        if len(pending_indices) == 0:
            pending_function_calls.pop(call_id, None)

    missing_outputs: list[tuple[int, str]] = []
    for call_id, pending_indices in pending_function_calls.items():
        for pending_index in pending_indices:
            missing_outputs.append((pending_index, call_id))

    for pending_index, call_id in sorted(missing_outputs, reverse=True):
        history.insert(
            pending_index + 1,
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": _MISSING_TOOL_OUTPUT_PLACEHOLDER,
            },
        )

    return history
