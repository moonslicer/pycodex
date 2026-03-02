from __future__ import annotations

from typing import Any

import pytest
from pycodex.protocol.events import (
    ApprovalRequested,
    ContextCompacted,
    ItemCompleted,
    ItemStarted,
    ItemUpdated,
    ProtocolEvent,
    ThreadStarted,
    TokenUsage,
    TurnCompleted,
    TurnFailed,
    TurnStarted,
    UsageSnapshot,
)
from pydantic import TypeAdapter, ValidationError


@pytest.mark.parametrize(
    ("event", "event_cls"),
    [
        (ThreadStarted(thread_id="thread_1"), ThreadStarted),
        (TurnStarted(thread_id="thread_1", turn_id="turn_1"), TurnStarted),
        (
            ContextCompacted(
                thread_id="thread_1",
                turn_id="turn_1",
                strategy="threshold_v1",
                implementation="local_summary_v1",
                replaced_items=6,
                estimated_prompt_tokens=9100,
                context_window_tokens=10000,
                remaining_ratio=0.09,
                threshold_ratio=0.2,
            ),
            ContextCompacted,
        ),
        (
            TurnCompleted(
                thread_id="thread_1",
                turn_id="turn_1",
                final_text="done",
                usage=UsageSnapshot(
                    turn=TokenUsage(input_tokens=10, output_tokens=5),
                    cumulative=TokenUsage(input_tokens=10, output_tokens=5),
                ),
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
        (
            ApprovalRequested(
                thread_id="thread_1",
                turn_id="turn_1",
                request_id="req_1",
                tool="write_file",
                preview='{"file_path":"notes.txt"}',
            ),
            ApprovalRequested,
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
                "type": "context.compacted",
                "thread_id": "thread_1",
                "turn_id": "turn_1",
                "strategy": "threshold_v1",
                "implementation": "local_summary_v1",
                "replaced_items": 6,
                "estimated_prompt_tokens": 9100,
                "context_window_tokens": 10000,
                "remaining_ratio": 0.09,
                "threshold_ratio": 0.2,
            },
            ContextCompacted,
        ),
        (
            {
                "type": "turn.completed",
                "thread_id": "thread_1",
                "turn_id": "turn_1",
                "final_text": "done",
                "usage": {
                    "turn": {"input_tokens": 3, "output_tokens": 2},
                    "cumulative": {"input_tokens": 11, "output_tokens": 7},
                },
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
        (
            {
                "type": "approval.request",
                "thread_id": "thread_1",
                "turn_id": "turn_1",
                "request_id": "req_1",
                "tool": "shell",
                "preview": "rm -f temp.txt",
            },
            ApprovalRequested,
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


def test_usage_snapshot_rejects_invalid_nested_values() -> None:
    with pytest.raises(ValidationError):
        UsageSnapshot.model_validate(
            {
                "turn": {"input_tokens": "10", "output_tokens": 5},
                "cumulative": {"input_tokens": 10, "output_tokens": 5},
            }
        )


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


def test_approval_requested_round_trip_json() -> None:
    event = ApprovalRequested(
        thread_id="thread_1",
        turn_id="turn_1",
        request_id="req_1",
        tool="shell",
        preview="rm -f temp.txt",
    )

    encoded = event.model_dump_json()
    decoded = ApprovalRequested.model_validate_json(encoded)
    assert decoded == event


def test_protocol_event_union_resolves_approval_requested() -> None:
    adapter = TypeAdapter(ProtocolEvent)
    event = adapter.validate_python(
        {
            "type": "approval.request",
            "thread_id": "thread_1",
            "turn_id": "turn_1",
            "request_id": "req_1",
            "tool": "shell",
            "preview": "rm -f temp.txt",
        }
    )

    assert isinstance(event, ApprovalRequested)
