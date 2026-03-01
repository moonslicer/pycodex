from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest
from openai.types.responses import ResponseCompletedEvent
from pycodex.core.config import Config
from pycodex.core.model_client import (
    Completed,
    ModelClient,
    ModelClientStreamError,
    OutputItemDone,
    OutputTextDelta,
)


class _FakeStream:
    def __init__(self, events: list[Any], error: Exception | None = None) -> None:
        self._events = events
        self._error = error
        self._index = 0
        self.closed = False

    def __aiter__(self) -> _FakeStream:
        return self

    async def __anext__(self) -> Any:
        if self._index < len(self._events):
            event = self._events[self._index]
            self._index += 1
            return event

        if self._error is not None:
            error = self._error
            self._error = None
            raise error

        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.closed = True


class _FakeResponses:
    def __init__(self, streams: list[_FakeStream]) -> None:
        self._streams = streams
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> _FakeStream:
        self.calls.append(kwargs)
        if not self._streams:
            raise AssertionError("No configured fake stream available for create()")
        return self._streams.pop(0)


@dataclass(slots=True)
class _FakeOpenAIClient:
    responses: _FakeResponses


class _TransientError(RuntimeError):
    status_code = 503


class _FatalError(RuntimeError):
    status_code = 400


async def _collect_events(client: ModelClient) -> list[Any]:
    events: list[Any] = []
    async for event in client.stream(
        messages=[{"role": "user", "content": "hello"}],
        tools=[{"type": "function", "function": {"name": "shell"}}],
    ):
        events.append(event)
    return events


def test_model_client_maps_events_to_typed_dataclasses() -> None:
    responses = _FakeResponses(
        streams=[
            _FakeStream(
                [
                    {
                        "type": "response.output_text.delta",
                        "delta": "hi",
                        "item_id": "msg_1",
                        "output_index": 0,
                    },
                    {
                        "type": "response.output_item.done",
                        "item": {
                            "type": "function_call",
                            "name": "read_file",
                            "arguments": '{"file_path":"README.md"}',
                            "call_id": "call_1",
                        },
                    },
                    {"type": "response.completed", "response": {"id": "resp_1"}},
                ]
            )
        ]
    )
    client = ModelClient(
        config=Config(model="gpt-test"),
        openai_factory=lambda _config: _FakeOpenAIClient(responses=responses),
    )

    events = asyncio.run(_collect_events(client))

    assert events == [
        OutputTextDelta(delta="hi", item_id="msg_1", output_index=0),
        OutputItemDone(
            item={
                "type": "function_call",
                "name": "read_file",
                "arguments": '{"file_path":"README.md"}',
                "call_id": "call_1",
            }
        ),
        Completed(response_id="resp_1"),
    ]
    assert len(responses.calls) == 1
    assert responses.calls[0]["model"] == "gpt-test"
    assert responses.calls[0]["stream"] is True
    assert isinstance(responses.calls[0]["input"], list)
    assert responses.calls[0]["tools"] == [{"type": "function", "name": "shell"}]


def test_model_client_omits_instructions_field_when_empty() -> None:
    responses = _FakeResponses(
        streams=[_FakeStream(events=[{"type": "response.completed", "response": {"id": "resp_1"}}])]
    )
    client = ModelClient(
        config=Config(model="gpt-test"),
        openai_factory=lambda _config: _FakeOpenAIClient(responses=responses),
    )

    async def _run() -> list[Any]:
        events: list[Any] = []
        async for event in client.stream(
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
            instructions="",
        ):
            events.append(event)
        return events

    events = asyncio.run(_run())

    assert events == [Completed(response_id="resp_1")]
    assert "instructions" not in responses.calls[0]


def test_model_client_includes_instructions_field_when_non_empty() -> None:
    responses = _FakeResponses(
        streams=[_FakeStream(events=[{"type": "response.completed", "response": {"id": "resp_1"}}])]
    )
    client = ModelClient(
        config=Config(model="gpt-test"),
        openai_factory=lambda _config: _FakeOpenAIClient(responses=responses),
    )

    async def _run() -> list[Any]:
        events: list[Any] = []
        async for event in client.stream(
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
            instructions="You are a test agent.",
        ):
            events.append(event)
        return events

    events = asyncio.run(_run())

    assert events == [Completed(response_id="resp_1")]
    assert responses.calls[0]["instructions"] == "You are a test agent."


def test_model_client_converts_function_call_and_tool_messages() -> None:
    responses = _FakeResponses(
        streams=[_FakeStream(events=[{"type": "response.completed", "response": {"id": "resp_1"}}])]
    )
    client = ModelClient(
        config=Config(model="gpt-test"),
        openai_factory=lambda _config: _FakeOpenAIClient(responses=responses),
    )

    async def _run() -> list[Any]:
        events: list[Any] = []
        async for event in client.stream(
            messages=[
                {"role": "user", "content": "hello"},
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "shell",
                    "arguments": '{"command":"echo hi"}',
                },
                {"role": "tool", "tool_call_id": "call_1", "content": '{"ok":true}'},
            ],
            tools=[],
        ):
            events.append(event)
        return events

    events = asyncio.run(_run())

    assert events == [Completed(response_id="resp_1")]
    assert responses.calls[0]["input"] == [
        {"role": "user", "content": "hello"},
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "shell",
            "arguments": '{"command":"echo hi"}',
        },
        {"type": "function_call_output", "call_id": "call_1", "output": '{"ok":true}'},
    ]


def test_model_client_retries_once_on_transient_stream_failure() -> None:
    responses = _FakeResponses(
        streams=[
            _FakeStream(events=[], error=_TransientError("temporary outage")),
            _FakeStream(events=[{"type": "response.completed", "response": {"id": "resp_ok"}}]),
        ]
    )
    client = ModelClient(
        config=Config(model="gpt-test"),
        openai_factory=lambda _config: _FakeOpenAIClient(responses=responses),
    )

    events = asyncio.run(_collect_events(client))

    assert events == [Completed(response_id="resp_ok")]
    assert len(responses.calls) == 2


def test_model_client_stops_after_retry_budget_is_exhausted() -> None:
    responses = _FakeResponses(
        streams=[
            _FakeStream(events=[], error=_TransientError("first outage")),
            _FakeStream(events=[], error=_TransientError("second outage")),
        ]
    )
    client = ModelClient(
        config=Config(model="gpt-test"),
        openai_factory=lambda _config: _FakeOpenAIClient(responses=responses),
    )

    with pytest.raises(
        ModelClientStreamError,
        match="Model stream failed after 2 attempt\\(s\\): second outage",
    ):
        asyncio.run(_collect_events(client))

    assert len(responses.calls) == 2


def test_model_client_does_not_retry_non_transient_stream_failure() -> None:
    responses = _FakeResponses(
        streams=[_FakeStream(events=[], error=_FatalError("bad request from server"))]
    )
    client = ModelClient(
        config=Config(model="gpt-test"),
        openai_factory=lambda _config: _FakeOpenAIClient(responses=responses),
    )

    with pytest.raises(
        ModelClientStreamError,
        match="Model stream failed after 1 attempt\\(s\\): bad request from server",
    ):
        asyncio.run(_collect_events(client))

    assert len(responses.calls) == 1


def test_model_client_does_not_retry_after_partial_stream_output() -> None:
    responses = _FakeResponses(
        streams=[
            _FakeStream(
                events=[{"type": "response.output_text.delta", "delta": "partial"}],
                error=_TransientError("connection dropped mid-stream"),
            ),
            _FakeStream(
                events=[{"type": "response.completed", "response": {"id": "should_not_run"}}]
            ),
        ]
    )
    client = ModelClient(
        config=Config(model="gpt-test"),
        openai_factory=lambda _config: _FakeOpenAIClient(responses=responses),
    )

    with pytest.raises(
        ModelClientStreamError,
        match="Model stream failed after 1 attempt\\(s\\): connection dropped mid-stream",
    ):
        asyncio.run(_collect_events(client))

    assert len(responses.calls) == 1


def test_model_client_raises_on_response_failed_event() -> None:
    responses = _FakeResponses(
        streams=[
            _FakeStream(
                events=[
                    {
                        "type": "response.failed",
                        "error": {
                            "code": "invalid_request_error",
                            "message": "tool output schema mismatch",
                        },
                    }
                ]
            )
        ]
    )
    client = ModelClient(
        config=Config(model="gpt-test"),
        openai_factory=lambda _config: _FakeOpenAIClient(responses=responses),
    )

    with pytest.raises(
        ModelClientStreamError,
        match="Model stream event failed: invalid_request_error: tool output schema mismatch",
    ):
        asyncio.run(_collect_events(client))

    assert len(responses.calls) == 1


def test_response_event_dataclasses_are_constructible() -> None:
    delta = OutputTextDelta(delta="x")
    item_done = OutputItemDone(item={"type": "message"})
    completed = Completed(response_id="resp-id")

    assert delta.type == "output_text_delta"
    assert item_done.type == "output_item_done"
    assert completed.type == "completed"


def test_model_client_maps_usage_on_completed_event() -> None:
    responses = _FakeResponses(
        streams=[
            _FakeStream(
                events=[
                    {
                        "type": "response.completed",
                        "response": {
                            "id": "resp_usage",
                            "usage": {"input_tokens": 10, "output_tokens": 5},
                        },
                    }
                ]
            )
        ]
    )
    client = ModelClient(
        config=Config(model="gpt-test"),
        openai_factory=lambda _config: _FakeOpenAIClient(responses=responses),
    )

    events = asyncio.run(_collect_events(client))

    assert events == [
        Completed(
            response_id="resp_usage",
            usage={"input_tokens": 10, "output_tokens": 5},
        )
    ]


def test_model_client_uses_none_when_completed_usage_is_missing() -> None:
    responses = _FakeResponses(
        streams=[
            _FakeStream(
                events=[
                    {
                        "type": "response.completed",
                        "response": {"id": "resp_no_usage"},
                    }
                ]
            )
        ]
    )
    client = ModelClient(
        config=Config(model="gpt-test"),
        openai_factory=lambda _config: _FakeOpenAIClient(responses=responses),
    )

    events = asyncio.run(_collect_events(client))

    assert events == [Completed(response_id="resp_no_usage", usage=None)]


def test_model_client_maps_usage_from_sdk_completed_event_object() -> None:
    sdk_completed = ResponseCompletedEvent.model_validate(
        {
            "type": "response.completed",
            "sequence_number": 1,
            "response": {
                "id": "resp_sdk_usage",
                "created_at": 0,
                "model": "gpt-4o-mini",
                "object": "response",
                "output": [],
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": [],
                "usage": {
                    "input_tokens": 10,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens": 5,
                    "output_tokens_details": {"reasoning_tokens": 0},
                    "total_tokens": 15,
                },
            },
        }
    )
    responses = _FakeResponses(streams=[_FakeStream(events=[sdk_completed])])
    client = ModelClient(
        config=Config(model="gpt-test"),
        openai_factory=lambda _config: _FakeOpenAIClient(responses=responses),
    )

    events = asyncio.run(_collect_events(client))

    assert events == [
        Completed(
            response_id="resp_sdk_usage",
            usage={"input_tokens": 10, "output_tokens": 5},
        )
    ]
