from __future__ import annotations

from typing import Any

import pytest
from pycodex.protocol.events import (
    ItemCompleted,
    ItemStarted,
    ItemUpdated,
    ProtocolEvent,
    ThreadStarted,
    TokenUsage,
    TurnCompleted,
    TurnFailed,
    TurnStarted,
)
from pydantic import TypeAdapter, ValidationError


@pytest.mark.parametrize(
    ("event", "event_cls"),
    [
        (ThreadStarted(thread_id="thread_1"), ThreadStarted),
        (TurnStarted(thread_id="thread_1", turn_id="turn_1"), TurnStarted),
        (
            TurnCompleted(
                thread_id="thread_1",
                turn_id="turn_1",
                final_text="done",
                usage=TokenUsage(input_tokens=10, output_tokens=5),
            ),
            TurnCompleted,
        ),
        (
            TurnFailed(
                thread_id="thread_1",
                turn_id="turn_1",
                error="boom",
            ),
            TurnFailed,
        ),
        (
            ItemStarted(
                thread_id="thread_1",
                turn_id="turn_1",
                item_id="call_1",
                item_kind="tool_call",
                name="shell",
                arguments='{"command":"pwd"}',
            ),
            ItemStarted,
        ),
        (
            ItemCompleted(
                thread_id="thread_1",
                turn_id="turn_1",
                item_id="call_1",
                item_kind="tool_result",
                content="ok",
            ),
            ItemCompleted,
        ),
        (
            ItemUpdated(
                thread_id="thread_1",
                turn_id="turn_1",
                item_id="msg_1",
                delta="hel",
            ),
            ItemUpdated,
        ),
    ],
)
def test_event_model_round_trip_json(event: Any, event_cls: type[Any]) -> None:
    encoded = event.model_dump_json()
    decoded = event_cls.model_validate_json(encoded)
    assert decoded == event


@pytest.mark.parametrize(
    ("payload", "expected_cls"),
    [
        ({"type": "thread.started", "thread_id": "thread_1"}, ThreadStarted),
        (
            {"type": "turn.started", "thread_id": "thread_1", "turn_id": "turn_1"},
            TurnStarted,
        ),
        (
            {
                "type": "turn.completed",
                "thread_id": "thread_1",
                "turn_id": "turn_1",
                "final_text": "done",
                "usage": {"input_tokens": 3, "output_tokens": 2},
            },
            TurnCompleted,
        ),
        (
            {
                "type": "turn.failed",
                "thread_id": "thread_1",
                "turn_id": "turn_1",
                "error": "boom",
            },
            TurnFailed,
        ),
        (
            {
                "type": "item.started",
                "thread_id": "thread_1",
                "turn_id": "turn_1",
                "item_id": "call_1",
                "item_kind": "assistant_message",
            },
            ItemStarted,
        ),
        (
            {
                "type": "item.completed",
                "thread_id": "thread_1",
                "turn_id": "turn_1",
                "item_id": "call_1",
                "item_kind": "assistant_message",
                "content": "done",
            },
            ItemCompleted,
        ),
        (
            {
                "type": "item.updated",
                "thread_id": "thread_1",
                "turn_id": "turn_1",
                "item_id": "msg_1",
                "delta": "hel",
            },
            ItemUpdated,
        ),
    ],
)
def test_protocol_event_union_resolves_type(
    payload: dict[str, Any], expected_cls: type[Any]
) -> None:
    adapter = TypeAdapter(ProtocolEvent)
    event = adapter.validate_python(payload)
    assert isinstance(event, expected_cls)


def test_token_usage_rejects_string_values() -> None:
    with pytest.raises(ValidationError):
        TokenUsage.model_validate({"input_tokens": "10", "output_tokens": 5})


@pytest.mark.parametrize("payload", [{"item_kind": "tool_output"}, {"item_kind": "unknown"}])
def test_item_kind_rejects_unknown_values(payload: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        ItemStarted.model_validate(
            {
                "thread_id": "thread_1",
                "turn_id": "turn_1",
                "item_id": "item_1",
                **payload,
            }
        )


def test_protocol_event_union_rejects_unknown_type() -> None:
    adapter = TypeAdapter(ProtocolEvent)
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                "type": "thread.unknown",
                "thread_id": "thread_1",
            }
        )


def test_item_updated_round_trip_json() -> None:
    event = ItemUpdated(
        thread_id="thread_1",
        turn_id="turn_1",
        item_id="msg_1",
        delta="hel",
    )

    encoded = event.model_dump_json()
    decoded = ItemUpdated.model_validate_json(encoded)
    assert decoded == event


def test_protocol_event_union_resolves_item_updated() -> None:
    adapter = TypeAdapter(ProtocolEvent)
    event = adapter.validate_python(
        {
            "type": "item.updated",
            "thread_id": "thread_1",
            "turn_id": "turn_1",
            "item_id": "msg_1",
            "delta": "hel",
        }
    )

    assert isinstance(event, ItemUpdated)
