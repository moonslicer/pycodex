from __future__ import annotations

import re

import pytest
from pycodex.core.agent import (
    ContextCompacted,
    TextDeltaReceived,
    ToolCallDispatched,
    ToolResultReceived,
    TurnCompleted,
    TurnStarted,
)
from pycodex.core.event_adapter import EventAdapter
from pycodex.protocol.events import (
    ContextCompacted as ProtocolContextCompacted,
)
from pycodex.protocol.events import (
    ItemCompleted,
    ItemStarted,
    ItemUpdated,
    ThreadStarted,
    TokenUsage,
    TurnFailed,
    UsageSnapshot,
)
from pycodex.protocol.events import TurnCompleted as ProtocolTurnCompleted
from pycodex.protocol.events import TurnStarted as ProtocolTurnStarted

ABORT_TEXT = "Aborted by user."
INTERRUPTED_ERROR = "interrupted"


def test_start_thread_emits_adapter_thread_id() -> None:
    adapter = EventAdapter(thread_id="thread_test")

    out = adapter.start_thread()

    assert isinstance(out, ThreadStarted)
    assert out.type == "thread.started"
    assert out.thread_id == "thread_test"


def test_start_thread_raises_when_called_more_than_once() -> None:
    adapter = EventAdapter(thread_id="thread_test")
    adapter.start_thread()

    with pytest.raises(RuntimeError, match="already been emitted"):
        adapter.start_thread()


def test_id_generation_and_reuse() -> None:
    adapter = EventAdapter(thread_id="thread_test")
    adapter.on_agent_event(TurnStarted(user_input="run"))

    started = adapter.on_agent_event(
        ToolCallDispatched(call_id="call_abc", name="shell", arguments='{"command":"pwd"}')
    )
    completed = adapter.on_agent_event(
        ToolResultReceived(call_id="call_abc", name="shell", result="ok")
    )

    assert len(started) == 1
    assert len(completed) == 1
    assert isinstance(started[0], ItemStarted)
    assert isinstance(completed[0], ItemCompleted)
    assert started[0].item_id == "call_abc"
    assert completed[0].item_id == "call_abc"


def test_id_fallback_when_call_id_empty() -> None:
    adapter = EventAdapter(thread_id="thread_test")
    adapter.on_agent_event(TurnStarted(user_input="run"))

    out = adapter.on_agent_event(
        ToolCallDispatched(call_id="", name="shell", arguments='{"command":"pwd"}')
    )

    assert len(out) == 1
    assert isinstance(out[0], ItemStarted)
    assert re.fullmatch(r"item_turn_1_1", out[0].item_id)


def test_no_tool_turn() -> None:
    adapter = EventAdapter(thread_id="thread_test")

    out_started = adapter.on_agent_event(TurnStarted(user_input="hello"))
    out_completed = adapter.on_agent_event(TurnCompleted(final_text="done"))
    out = [*out_started, *out_completed]

    assert [event.type for event in out] == ["turn.started", "turn.completed"]


def test_item_updated_emits_with_model_item_id() -> None:
    adapter = EventAdapter(thread_id="thread_test")
    adapter.on_agent_event(TurnStarted(user_input="hello"))

    out = adapter.on_agent_event(
        TextDeltaReceived(
            delta="hel",
            item_id="msg_1",
        )
    )

    assert len(out) == 1
    assert isinstance(out[0], ItemUpdated)
    assert out[0].item_id == "msg_1"
    assert out[0].delta == "hel"


def test_item_updated_reuses_generated_item_id_for_missing_source_id() -> None:
    adapter = EventAdapter(thread_id="thread_test")
    adapter.on_agent_event(TurnStarted(user_input="hello"))

    first = adapter.on_agent_event(TextDeltaReceived(delta="line one"))
    second = adapter.on_agent_event(TextDeltaReceived(delta="line two"))

    assert len(first) == 1
    assert len(second) == 1
    assert isinstance(first[0], ItemUpdated)
    assert isinstance(second[0], ItemUpdated)
    assert first[0].item_id == second[0].item_id
    assert first[0].delta == "line one"
    assert second[0].delta == "line two"


def test_item_updated_generated_item_id_resets_between_turns() -> None:
    adapter = EventAdapter(thread_id="thread_test")
    adapter.on_agent_event(TurnStarted(user_input="hello"))
    first = adapter.on_agent_event(TextDeltaReceived(delta="turn one"))
    adapter.on_agent_event(TurnCompleted(final_text="done"))
    adapter.on_agent_event(TurnStarted(user_input="hello again"))
    second = adapter.on_agent_event(TextDeltaReceived(delta="turn two"))

    assert len(first) == 1
    assert len(second) == 1
    assert isinstance(first[0], ItemUpdated)
    assert isinstance(second[0], ItemUpdated)
    assert first[0].item_id != second[0].item_id


def test_single_tool_call_turn() -> None:
    adapter = EventAdapter(thread_id="thread_test")

    out: list[object] = []
    out.extend(adapter.on_agent_event(TurnStarted(user_input="run")))
    out.extend(
        adapter.on_agent_event(
            ToolCallDispatched(call_id="call_1", name="shell", arguments='{"command":"pwd"}')
        )
    )
    out.extend(
        adapter.on_agent_event(ToolResultReceived(call_id="call_1", name="shell", result="ok"))
    )
    out.extend(adapter.on_agent_event(TurnCompleted(final_text="done")))

    assert [event.type for event in out] == [
        "turn.started",
        "item.started",
        "item.completed",
        "turn.completed",
    ]


def test_multi_tool_call_turn() -> None:
    adapter = EventAdapter(thread_id="thread_test")

    out: list[object] = []
    out.extend(adapter.on_agent_event(TurnStarted(user_input="run")))
    out.extend(
        adapter.on_agent_event(
            ToolCallDispatched(call_id="call_1", name="shell", arguments='{"command":"pwd"}')
        )
    )
    out.extend(
        adapter.on_agent_event(ToolResultReceived(call_id="call_1", name="shell", result="ok-1"))
    )
    out.extend(
        adapter.on_agent_event(
            ToolCallDispatched(call_id="call_2", name="read_file", arguments='{"file_path":"a"}')
        )
    )
    out.extend(
        adapter.on_agent_event(
            ToolResultReceived(call_id="call_2", name="read_file", result="ok-2")
        )
    )
    out.extend(adapter.on_agent_event(TurnCompleted(final_text="done")))

    assert [event.type for event in out] == [
        "turn.started",
        "item.started",
        "item.completed",
        "item.started",
        "item.completed",
        "turn.completed",
    ]
    started_ids = [event.item_id for event in out if isinstance(event, ItemStarted)]
    completed_ids = [event.item_id for event in out if isinstance(event, ItemCompleted)]
    assert started_ids == ["call_1", "call_2"]
    assert completed_ids == ["call_1", "call_2"]


def test_turn_counter_increments() -> None:
    adapter = EventAdapter(thread_id="thread_test")

    first = adapter.on_agent_event(TurnStarted(user_input="first"))
    adapter.on_agent_event(TurnCompleted(final_text="done-1"))
    second = adapter.on_agent_event(TurnStarted(user_input="second"))

    assert len(first) == 1
    assert len(second) == 1
    assert isinstance(first[0], ProtocolTurnStarted)
    assert isinstance(second[0], ProtocolTurnStarted)
    assert first[0].turn_id == "turn_1"
    assert second[0].turn_id == "turn_2"


def test_failure_turn_id_without_active_turn_uses_next_turn() -> None:
    adapter = EventAdapter(thread_id="thread_test")

    assert adapter.failure_turn_id() == "turn_1"


def test_failure_turn_id_with_active_turn_uses_current_turn() -> None:
    adapter = EventAdapter(thread_id="thread_test")
    adapter.on_agent_event(TurnStarted(user_input="run"))

    assert adapter.failure_turn_id() == "turn_1"


def test_turn_failed_without_active_turn_uses_next_turn_and_exception_message() -> None:
    adapter = EventAdapter(thread_id="thread_test")

    out = adapter.turn_failed(RuntimeError("boom"))

    assert isinstance(out, TurnFailed)
    assert out.thread_id == "thread_test"
    assert out.turn_id == "turn_1"
    assert out.error == "boom"


def test_turn_failed_with_active_turn_uses_current_turn_and_fallback_error_name() -> None:
    adapter = EventAdapter(thread_id="thread_test")
    adapter.on_agent_event(TurnStarted(user_input="run"))

    out = adapter.turn_failed(RuntimeError())

    assert isinstance(out, TurnFailed)
    assert out.thread_id == "thread_test"
    assert out.turn_id == "turn_1"
    assert out.error == "RuntimeError"


@pytest.mark.parametrize(
    ("scenario", "expected_type"),
    [
        ("abort", "turn.completed"),
        ("interrupt", "turn.failed"),
    ],
)
def test_abort_interrupt_terminal_mapping(scenario: str, expected_type: str) -> None:
    adapter = EventAdapter(thread_id="thread_test")
    adapter.on_agent_event(TurnStarted(user_input=scenario))

    if scenario == "abort":
        out = adapter.on_agent_event(TurnCompleted(final_text=ABORT_TEXT))
        assert len(out) == 1
        event = out[0]
    else:
        event = adapter.turn_failed(INTERRUPTED_ERROR)

    assert event.type == expected_type
    assert event.turn_id == "turn_1"
    if expected_type == "turn.completed":
        assert isinstance(event, ProtocolTurnCompleted)
    else:
        assert isinstance(event, TurnFailed)
        assert event.error == INTERRUPTED_ERROR


def test_usage_in_turn_completed() -> None:
    adapter = EventAdapter(thread_id="thread_test")
    adapter.on_agent_event(TurnStarted(user_input="hello"))

    out = adapter.on_agent_event(
        TurnCompleted(
            final_text="done",
            usage={
                "turn": {"input_tokens": 10, "output_tokens": 5},
                "cumulative": {"input_tokens": 15, "output_tokens": 8},
            },
        )
    )

    assert len(out) == 1
    assert isinstance(out[0], ProtocolTurnCompleted)
    assert out[0].usage == UsageSnapshot(
        turn=TokenUsage(input_tokens=10, output_tokens=5),
        cumulative=TokenUsage(input_tokens=15, output_tokens=8),
    )


def test_usage_none_when_absent() -> None:
    adapter = EventAdapter(thread_id="thread_test")
    adapter.on_agent_event(TurnStarted(user_input="hello"))

    out = adapter.on_agent_event(TurnCompleted(final_text="done", usage=None))

    assert len(out) == 1
    assert isinstance(out[0], ProtocolTurnCompleted)
    assert out[0].usage is None


def test_injectable_thread_id() -> None:
    adapter = EventAdapter(thread_id="test-thread-1")
    out: list[object] = []
    out.extend(adapter.on_agent_event(TurnStarted(user_input="hello")))
    out.extend(
        adapter.on_agent_event(
            ToolCallDispatched(call_id="call_1", name="shell", arguments='{"command":"pwd"}')
        )
    )
    out.extend(
        adapter.on_agent_event(ToolResultReceived(call_id="call_1", name="shell", result="ok"))
    )
    out.extend(adapter.on_agent_event(TurnCompleted(final_text="done")))

    for event in out:
        assert hasattr(event, "thread_id")
        assert event.thread_id == "test-thread-1"


def test_arguments_dict_are_serialized_as_stable_json() -> None:
    adapter = EventAdapter(thread_id="thread_test")
    adapter.on_agent_event(TurnStarted(user_input="hello"))

    out = adapter.on_agent_event(
        ToolCallDispatched(
            call_id="call_1",
            name="shell",
            arguments={"b": 2, "a": 1},
        )
    )

    assert len(out) == 1
    assert isinstance(out[0], ItemStarted)
    assert out[0].arguments == '{"a": 1, "b": 2}'


def test_context_compacted_maps_to_protocol_event() -> None:
    adapter = EventAdapter(thread_id="thread_test")
    adapter.on_agent_event(TurnStarted(user_input="hello"))

    out = adapter.on_agent_event(
        ContextCompacted(
            strategy="threshold_v1",
            implementation="local_summary_v1",
            replaced_items=12,
            estimated_prompt_tokens=9800,
            context_window_tokens=10000,
            remaining_ratio=0.02,
            threshold_ratio=0.2,
        )
    )

    assert len(out) == 1
    assert isinstance(out[0], ProtocolContextCompacted)
    assert out[0].thread_id == "thread_test"
    assert out[0].turn_id == "turn_1"
    assert out[0].strategy == "threshold_v1"
    assert out[0].implementation == "local_summary_v1"
    assert out[0].replaced_items == 12
    assert out[0].estimated_prompt_tokens == 9800
    assert out[0].context_window_tokens == 10000


def test_turn_id_cleared_after_turn_completed() -> None:
    adapter = EventAdapter(thread_id="thread_test")
    adapter.on_agent_event(TurnStarted(user_input="hello"))
    adapter.on_agent_event(TurnCompleted(final_text="done"))

    # After TurnCompleted, _current_turn_id must be None so a stale ID cannot
    # be silently stamped onto approval or other post-turn events.
    with pytest.raises(RuntimeError, match="without active turn"):
        adapter.on_agent_event(TextDeltaReceived(delta="stale"))


def test_non_start_events_require_active_turn() -> None:
    adapter = EventAdapter(thread_id="thread_test")

    with pytest.raises(RuntimeError, match="without active turn"):
        adapter.on_agent_event(
            ToolCallDispatched(
                call_id="call_1",
                name="shell",
                arguments='{"command":"pwd"}',
            )
        )

    with pytest.raises(RuntimeError, match="without active turn"):
        adapter.on_agent_event(ToolResultReceived(call_id="call_1", name="shell", result="ok"))

    with pytest.raises(RuntimeError, match="without active turn"):
        adapter.on_agent_event(TextDeltaReceived(delta="hi"))

    with pytest.raises(RuntimeError, match="without active turn"):
        adapter.on_agent_event(TurnCompleted(final_text="done"))

    with pytest.raises(RuntimeError, match="without active turn"):
        adapter.on_agent_event(
            ContextCompacted(
                strategy="threshold_v1",
                implementation="local_summary_v1",
                replaced_items=2,
                estimated_prompt_tokens=9000,
                context_window_tokens=10000,
                remaining_ratio=0.1,
                threshold_ratio=0.2,
            )
        )
