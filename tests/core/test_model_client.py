from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest
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
                            "arguments": "{\"file_path\":\"README.md\"}",
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
                "arguments": "{\"file_path\":\"README.md\"}",
                "call_id": "call_1",
            }
        ),
        Completed(response_id="resp_1"),
    ]
    assert len(responses.calls) == 1
    assert responses.calls[0]["model"] == "gpt-test"
    assert responses.calls[0]["stream"] is True
    assert isinstance(responses.calls[0]["input"], list)
    assert isinstance(responses.calls[0]["tools"], list)


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


def test_response_event_dataclasses_are_constructible() -> None:
    delta = OutputTextDelta(delta="x")
    item_done = OutputItemDone(item={"type": "message"})
    completed = Completed(response_id="resp-id")

    assert delta.type == "output_text_delta"
    assert item_done.type == "output_item_done"
    assert completed.type == "completed"

