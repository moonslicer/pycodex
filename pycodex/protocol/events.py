"""Canonical protocol events for JSONL mode."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class _FrozenModel(BaseModel):
    """Base model for immutable protocol payloads."""

    model_config = ConfigDict(frozen=True)


class TokenUsage(_FrozenModel):
    """Token usage metrics for one completed turn."""

    input_tokens: StrictInt
    output_tokens: StrictInt


class UsageSnapshot(_FrozenModel):
    """Per-turn and cumulative token usage at turn completion."""

    turn: TokenUsage
    cumulative: TokenUsage


class ThreadStarted(_FrozenModel):
    """Event emitted at the start of a thread/session."""

    type: Literal["thread.started"] = "thread.started"
    thread_id: str


class TurnStarted(_FrozenModel):
    """Event emitted at the start of a turn."""

    type: Literal["turn.started"] = "turn.started"
    thread_id: str
    turn_id: str


class ContextCompacted(_FrozenModel):
    """Event emitted when context history was compacted for the active turn."""

    type: Literal["context.compacted"] = "context.compacted"
    thread_id: str
    turn_id: str
    strategy: str
    implementation: str
    replaced_items: StrictInt
    estimated_prompt_tokens: StrictInt
    context_window_tokens: StrictInt
    remaining_ratio: float
    threshold_ratio: float


class TurnCompleted(_FrozenModel):
    """Event emitted when a turn completes successfully."""

    type: Literal["turn.completed"] = "turn.completed"
    thread_id: str
    turn_id: str
    final_text: str
    usage: UsageSnapshot | None = None


class TurnFailed(_FrozenModel):
    """Event emitted when a turn fails."""

    type: Literal["turn.failed"] = "turn.failed"
    thread_id: str
    turn_id: str
    error: str


class ItemStarted(_FrozenModel):
    """Event emitted when an item starts within a turn."""

    type: Literal["item.started"] = "item.started"
    thread_id: str
    turn_id: str
    item_id: str
    item_kind: Literal["tool_call", "assistant_message"]
    name: str | None = None
    arguments: str | None = None


class ItemCompleted(_FrozenModel):
    """Event emitted when an item completes within a turn."""

    type: Literal["item.completed"] = "item.completed"
    thread_id: str
    turn_id: str
    item_id: str
    item_kind: Literal["tool_result", "assistant_message"]
    content: str


class ItemUpdated(_FrozenModel):
    """Event emitted when an item receives incremental content updates."""

    type: Literal["item.updated"] = "item.updated"
    thread_id: str
    turn_id: str
    item_id: str
    delta: str


class ApprovalRequested(_FrozenModel):
    """Event emitted when a mutating tool call requires user approval."""

    type: Literal["approval.request"] = "approval.request"
    thread_id: str
    turn_id: str
    request_id: str
    tool: str
    preview: str


ProtocolEvent: TypeAlias = Annotated[
    ThreadStarted
    | TurnStarted
    | ContextCompacted
    | TurnCompleted
    | TurnFailed
    | ItemStarted
    | ItemCompleted
    | ItemUpdated
    | ApprovalRequested,
    Field(discriminator="type"),
]
