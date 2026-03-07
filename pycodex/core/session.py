"""Session state and prompt history management for agent turns."""

from __future__ import annotations

import json
import logging
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypedDict
from uuid import uuid4

from pycodex.core.config import Config
from pycodex.core.rollout_recorder import RolloutRecorder
from pycodex.core.rollout_schema import RolloutItem, SessionClosed, TokenUsage

_log = logging.getLogger(__name__)

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


class TokenUsageCounts(TypedDict):
    """Token usage counters for one scope."""

    input_tokens: int
    output_tokens: int


class UsageSnapshot(TypedDict):
    """Per-turn and cumulative token usage snapshot."""

    turn: TokenUsageCounts
    cumulative: TokenUsageCounts


@dataclass(slots=True)
class Session:
    """Container for conversation history used to build model prompts."""

    config: Config | None = None
    thread_id: str = field(default_factory=lambda: str(uuid4()))
    _history: list[PromptItem] = field(default_factory=list)
    _initial_context_injected: bool = False
    _total_input_tokens: int = 0
    _total_output_tokens: int = 0
    _turn_count: int = 0
    _last_user_message: str | None = None
    _rollout_recorder: RolloutRecorder | None = None
    _rollout_path: Path | None = None
    _rollout_meta_written: bool = False
    _rollout_closed: bool = False

    def append_user_message(self, text: str) -> None:
        """Append a user message to the conversation history."""
        self._last_user_message = text
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

    def latest_history_item(self) -> PromptItem | None:
        """Return the most recently appended history item, if present."""
        if len(self._history) == 0:
            return None
        return self._history[-1].copy()

    def prepend_items(self, items: list[PromptItem]) -> None:
        """Prepend prompt items before existing session history."""
        self._history = list(items) + self._history

    def restore_from_rollout(
        self,
        *,
        history: list[PromptItem],
        cumulative_usage: dict[str, int],
        turn_count: int,
    ) -> None:
        """Restore session state from replayed rollout records."""
        self._history = [item.copy() for item in history]
        self._total_input_tokens = max(0, int(cumulative_usage.get("input_tokens", 0)))
        self._total_output_tokens = max(0, int(cumulative_usage.get("output_tokens", 0)))
        self._turn_count = max(0, turn_count)

    def replace_prefix_with_system_summary(self, *, replace_count: int, summary_text: str) -> bool:
        """Replace a leading history slice with one system summary message."""
        if replace_count <= 0:
            return False
        effective_replace_count = min(replace_count, len(self._history))
        if effective_replace_count == 0:
            return False
        self._history = [
            {"role": "system", "content": summary_text},
            *self._history[effective_replace_count:],
        ]
        return True

    def has_initial_context(self) -> bool:
        """Return whether initial context has already been injected."""
        return self._initial_context_injected

    def mark_initial_context_injected(self) -> None:
        """Mark initial context as injected for this session."""
        self._initial_context_injected = True

    def record_turn_usage(self, usage: dict[str, int] | None) -> UsageSnapshot | None:
        """Record one turn's usage and return an updated snapshot."""
        turn_usage = _normalize_usage_counts(usage)
        if turn_usage is None:
            return None

        self._total_input_tokens += turn_usage["input_tokens"]
        self._total_output_tokens += turn_usage["output_tokens"]
        cumulative_usage: TokenUsageCounts = {
            "input_tokens": self._total_input_tokens,
            "output_tokens": self._total_output_tokens,
        }
        return {
            "turn": turn_usage,
            "cumulative": cumulative_usage,
        }

    def mark_turn_completed(self) -> None:
        """Increment completed turn count."""
        self._turn_count += 1

    def completed_turn_count(self) -> int:
        """Return number of completed turns recorded in this session."""
        return self._turn_count

    def last_user_message(self) -> str | None:
        """Return the most recent user message text, if any."""
        return self._last_user_message

    def configure_rollout_recorder(
        self,
        *,
        recorder: RolloutRecorder,
        path: Path,
    ) -> None:
        """Enable rollout persistence with a recorder owned by this session."""
        self._rollout_recorder = recorder
        self._rollout_path = path

    def rollout_recorder(self) -> RolloutRecorder | None:
        """Return the configured rollout recorder, if persistence is enabled."""
        return self._rollout_recorder

    def rollout_path(self) -> Path | None:
        """Return configured rollout path, if persistence is enabled."""
        return self._rollout_path

    def rollout_meta_written(self) -> bool:
        """Return whether session.meta has been persisted."""
        return self._rollout_meta_written

    def mark_rollout_meta_written(self) -> None:
        """Mark session.meta as persisted."""
        self._rollout_meta_written = True

    async def record_rollout_items(self, items: Sequence[RolloutItem]) -> None:
        """Append rollout records when persistence is enabled."""
        recorder = self._rollout_recorder
        if recorder is None:
            return
        await recorder.record(items)

    async def flush_rollout(self) -> None:
        """Flush pending rollout records when persistence is enabled."""
        recorder = self._rollout_recorder
        if recorder is None:
            return
        await recorder.flush()

    async def close_rollout(self) -> None:
        """Persist session.closed and shutdown recorder on clean exit."""
        recorder = self._rollout_recorder
        if recorder is None or self._rollout_closed:
            return
        closed_at = datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        await recorder.record(
            [
                SessionClosed(
                    schema_version="1.0",
                    thread_id=self.thread_id,
                    closed_at=closed_at,
                    last_user_message=self._last_user_message,
                    turn_count=self._turn_count,
                    token_total=TokenUsage(
                        input_tokens=self._total_input_tokens,
                        output_tokens=self._total_output_tokens,
                    ),
                )
            ]
        )
        await recorder.shutdown()
        self._rollout_closed = True

    async def __aenter__(self) -> Session:
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        try:
            await self.close_rollout()
        except Exception as cleanup_exc:
            if exc_type is None:
                raise
            _log.warning("close_rollout() failed during context manager exit: %s", cleanup_exc)

    def cumulative_usage(self) -> TokenUsageCounts:
        """Return cumulative usage totals for the session."""
        return {
            "input_tokens": self._total_input_tokens,
            "output_tokens": self._total_output_tokens,
        }

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


def _normalize_usage_counts(usage: dict[str, int] | None) -> TokenUsageCounts | None:
    if usage is None:
        return None

    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if (
        not isinstance(input_tokens, int)
        or isinstance(input_tokens, bool)
        or input_tokens < 0
        or not isinstance(output_tokens, int)
        or isinstance(output_tokens, bool)
        or output_tokens < 0
    ):
        return None

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
