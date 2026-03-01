from __future__ import annotations

from typing import Any

from pycodex.core.config import Config
from pycodex.core.fake_model_client import FakeModelClient, _is_mutation_prompt
from pycodex.core.model_client import Completed, OutputItemDone, OutputTextDelta


async def _collect_events(client: FakeModelClient, user_text: str) -> list[Any]:
    messages: list[dict[str, str]] = [
        {"role": "user", "content": user_text},
    ]
    events: list[Any] = []
    async for event in client.stream(messages=messages, tools=[]):
        events.append(event)
    return events


def test_is_mutation_prompt_requires_exact_verification_phrase() -> None:
    assert _is_mutation_prompt("create a file for approval test") is True


def test_is_mutation_prompt_rejects_generic_mutation_words() -> None:
    assert _is_mutation_prompt("please explain how to save a file") is False
    assert _is_mutation_prompt("what does write_file do?") is False
    assert _is_mutation_prompt("can you help with file approval flows?") is False


async def test_fake_model_client_does_not_call_write_file_for_benign_prompt(tmp_path) -> None:
    client = FakeModelClient(
        Config(model="test-model", api_key="test-key", cwd=tmp_path),
    )

    events = await _collect_events(client, "please explain how to save a file")

    assert any(isinstance(event, OutputItemDone) for event in events) is False
    assert any(
        isinstance(event, OutputTextDelta) and event.delta == "FAKE_MODEL_OK" for event in events
    )
    assert any(isinstance(event, Completed) for event in events)


async def test_fake_model_client_calls_write_file_only_for_verification_phrase(tmp_path) -> None:
    client = FakeModelClient(
        Config(model="test-model", api_key="test-key", cwd=tmp_path),
    )

    events = await _collect_events(client, "create a file for approval test")

    tool_calls = [
        event.item
        for event in events
        if isinstance(event, OutputItemDone) and isinstance(event.item, dict)
    ]
    assert len(tool_calls) == 1
    assert tool_calls[0]["type"] == "function_call"
    assert tool_calls[0]["name"] == "write_file"
