from __future__ import annotations

import re

import pytest
from pycodex.core.agent import ToolCallDispatched, ToolResultReceived, TurnCompleted, TurnStarted
from pycodex.core.event_adapter import EventAdapter
from pycodex.protocol.events import ItemCompleted, ItemStarted
from pycodex.protocol.events import TurnCompleted as ProtocolTurnCompleted
from pycodex.protocol.events import TurnStarted as ProtocolTurnStarted


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


def test_abort_turn_emits_turn_completed_not_failed() -> None:
    adapter = EventAdapter(thread_id="thread_test")
    adapter.on_agent_event(TurnStarted(user_input="abort"))

    out = adapter.on_agent_event(TurnCompleted(final_text="Aborted by user."))

    assert len(out) == 1
    assert isinstance(out[0], ProtocolTurnCompleted)
    assert out[0].type == "turn.completed"


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
        adapter.on_agent_event(TurnCompleted(final_text="done"))
