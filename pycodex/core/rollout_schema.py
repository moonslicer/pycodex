"""Schema models for append-only JSONL session rollout records."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictInt, TypeAdapter

SCHEMA_VERSION: Literal["1.0"] = "1.0"


class _FrozenModel(BaseModel):
    """Base model for immutable rollout payloads."""

    model_config = ConfigDict(frozen=True)


class TokenUsage(_FrozenModel):
    """Token usage metrics for one snapshot scope."""

    input_tokens: StrictInt
    output_tokens: StrictInt


class UsageSnapshot(_FrozenModel):
    """Per-turn and cumulative token usage captured at turn completion."""

    turn: TokenUsage
    cumulative: TokenUsage


class SessionMeta(_FrozenModel):
    """Session-open metadata written once at rollout creation."""

    schema_version: Literal["1.0"]
    type: Literal["session.meta"] = "session.meta"
    thread_id: str
    profile: str
    model: str
    cwd: str
    opened_at: str
    import_source: str | None = None


class HistoryItem(_FrozenModel):
    """One persisted prompt-history item."""

    schema_version: Literal["1.0"]
    type: Literal["history.item"] = "history.item"
    thread_id: str
    item: dict[str, Any]


class TurnCompleted(_FrozenModel):
    """Turn-level usage snapshot persisted after successful completion."""

    schema_version: Literal["1.0"]
    type: Literal["turn.completed"] = "turn.completed"
    thread_id: str
    usage: UsageSnapshot


class CompactionApplied(_FrozenModel):
    """Record of one applied compaction replacement."""

    schema_version: Literal["1.0"]
    type: Literal["compaction.applied"] = "compaction.applied"
    thread_id: str
    summary_text: str
    replace_end: StrictInt
    replaced_items: StrictInt
    strategy: str
    implementation: str
    strategy_options: dict[str, Any]
    implementation_options: dict[str, Any]


class SessionClosed(_FrozenModel):
    """Session-close summary record for fast closed-session reads."""

    schema_version: Literal["1.0"]
    type: Literal["session.closed"] = "session.closed"
    thread_id: str
    closed_at: str
    last_user_message: str | None = None
    turn_count: StrictInt
    token_total: TokenUsage


RolloutItem: TypeAlias = Annotated[
    SessionMeta | HistoryItem | TurnCompleted | CompactionApplied | SessionClosed,
    Field(discriminator="type"),
]

_ROLLOUT_ITEM_ADAPTER: TypeAdapter[RolloutItem] = TypeAdapter(RolloutItem)


def validate_rollout_item(data: dict[str, Any]) -> RolloutItem:
    """Validate and parse one rollout JSON object."""

    return _ROLLOUT_ITEM_ADAPTER.validate_python(data)
