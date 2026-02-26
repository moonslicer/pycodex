"""Session state and prompt history management for agent turns."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypedDict

from pycodex.core.config import Config

MAX_TOOL_RESULT_CHARS = 200_000


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


PromptItem = UserMessageItem | AssistantMessageItem | SystemMessageItem | ToolResultMessageItem


@dataclass(slots=True)
class Session:
    """Container for conversation history used to build model prompts."""

    config: Config | None = None
    _history: list[PromptItem] = field(default_factory=list)

    def append_user_message(self, text: str) -> None:
        """Append a user message to the conversation history."""
        self._history.append({"role": "user", "content": text})

    def append_tool_result(self, call_id: str, result: str) -> None:
        """Append a tool result to the conversation history."""
        content = result
        if len(content) > MAX_TOOL_RESULT_CHARS:
            content = f"{content[:MAX_TOOL_RESULT_CHARS]}\n...[truncated by session history cap]"
        self._history.append({"role": "tool", "tool_call_id": call_id, "content": content})

    def to_prompt(self) -> list[PromptItem]:
        """Return a detached copy of history for model input payloads."""
        return [item.copy() for item in self._history]
