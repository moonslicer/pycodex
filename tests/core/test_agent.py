from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pycodex.core.agent import (
    AgentEvent,
    ToolCallDispatched,
    ToolResultReceived,
    TurnCompleted,
    TurnStarted,
    run_turn,
)
from pycodex.core.model_client import Completed, OutputItemDone, OutputTextDelta, ResponseEvent
from pycodex.core.session import Session
from pycodex.tools.orchestrator import ToolAborted


class _FakeModelClient:
    def __init__(self, turns: list[list[ResponseEvent]]) -> None:
        self._turns = turns
        self.calls: list[dict[str, Any]] = []

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ):
        self.calls.append(
            {
                "messages": [dict(message) for message in messages],
                "tools": [dict(spec) for spec in tools],
            }
        )

        if not self._turns:
            raise AssertionError("No configured turn events left")

        for event in self._turns.pop(0):
            yield event


@dataclass(slots=True)
class _FakeToolRouter:
    specs: list[dict[str, Any]]
    results: list[str]
    dispatch_calls: list[dict[str, Any]] = field(default_factory=list, init=False)
    _result_idx: int = field(default=0, init=False)

    def tool_specs(self) -> list[dict[str, Any]]:
        return [dict(spec) for spec in self.specs]

    async def dispatch(self, *, name: str, arguments: str | dict[str, Any], cwd: Path) -> str:
        self.dispatch_calls.append({"name": name, "arguments": arguments, "cwd": cwd})
        if self._result_idx >= len(self.results):
            return f"default:{name}"
        result = self.results[self._result_idx]
        self._result_idx += 1
        return result


@dataclass(slots=True)
class _AbortingToolRouter:
    specs: list[dict[str, Any]]
    dispatch_calls: list[dict[str, Any]] = field(default_factory=list, init=False)

    def tool_specs(self) -> list[dict[str, Any]]:
        return [dict(spec) for spec in self.specs]

    async def dispatch(self, *, name: str, arguments: str | dict[str, Any], cwd: Path) -> str:
        self.dispatch_calls.append({"name": name, "arguments": arguments, "cwd": cwd})
        raise ToolAborted(name)


def test_run_turn_returns_text_when_no_tool_calls(tmp_path: Path) -> None:
    session = Session()
    model_client = _FakeModelClient(
        turns=[
            [
                OutputTextDelta(delta="hello "),
                OutputTextDelta(delta="world"),
                Completed(response_id="resp_1"),
            ]
        ]
    )
    router = _FakeToolRouter(
        specs=[{"type": "function", "function": {"name": "read_file"}}], results=[]
    )

    result = asyncio.run(
        run_turn(
            session=session,
            model_client=model_client,
            tool_router=router,
            cwd=tmp_path,
            user_input="say hi",
        )
    )

    assert result == "hello world"
    assert router.dispatch_calls == []
    assert model_client.calls == [
        {
            "messages": [{"role": "user", "content": "say hi"}],
            "tools": [{"type": "function", "function": {"name": "read_file"}}],
        }
    ]
    assert session.to_prompt() == [{"role": "user", "content": "say hi"}]


def test_run_turn_executes_tool_calls_and_loops(tmp_path: Path) -> None:
    session = Session()
    model_client = _FakeModelClient(
        turns=[
            [
                OutputItemDone(
                    item={
                        "type": "function_call",
                        "name": "read_file",
                        "arguments": '{"file_path":"README.md"}',
                        "call_id": "call_1",
                    }
                ),
                Completed(response_id="resp_tools"),
            ],
            [
                OutputTextDelta(delta="done"),
                Completed(response_id="resp_final"),
            ],
        ]
    )
    router = _FakeToolRouter(
        specs=[{"type": "function", "function": {"name": "read_file"}}],
        results=["L1: # pycodex"],
    )

    result = asyncio.run(
        run_turn(
            session=session,
            model_client=model_client,
            tool_router=router,
            cwd=tmp_path,
            user_input="read README",
        )
    )

    assert result == "done"
    assert len(router.dispatch_calls) == 1
    assert router.dispatch_calls[0] == {
        "name": "read_file",
        "arguments": '{"file_path":"README.md"}',
        "cwd": tmp_path,
    }
    assert model_client.calls[1]["messages"] == [
        {"role": "user", "content": "read README"},
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "read_file",
            "arguments": '{"file_path":"README.md"}',
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "L1: # pycodex"},
    ]
    assert session.to_prompt() == [
        {"role": "user", "content": "read README"},
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "read_file",
            "arguments": '{"file_path":"README.md"}',
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "L1: # pycodex"},
    ]


def test_run_turn_emits_lifecycle_events_in_order(tmp_path: Path) -> None:
    session = Session()
    model_client = _FakeModelClient(
        turns=[
            [
                OutputItemDone(
                    item={
                        "type": "function_call",
                        "name": "shell",
                        "arguments": '{"command":"echo hi"}',
                        "call_id": "call_99",
                    }
                ),
                Completed(response_id="resp_tools"),
            ],
            [OutputTextDelta(delta="final"), Completed(response_id="resp_final")],
        ]
    )
    router = _FakeToolRouter(
        specs=[{"type": "function", "function": {"name": "shell"}}],
        results=["stdout:\nhi"],
    )
    emitted: list[AgentEvent] = []

    async def on_event(event: AgentEvent) -> None:
        emitted.append(event)

    result = asyncio.run(
        run_turn(
            session=session,
            model_client=model_client,
            tool_router=router,
            cwd=tmp_path,
            user_input="run shell",
            on_event=on_event,
        )
    )

    assert result == "final"
    assert [event.type for event in emitted] == [
        "turn_started",
        "tool_call_dispatched",
        "tool_result_received",
        "turn_completed",
    ]
    assert isinstance(emitted[0], TurnStarted)
    assert emitted[0].user_input == "run shell"
    assert isinstance(emitted[1], ToolCallDispatched)
    assert emitted[1].call_id == "call_99"
    assert emitted[1].name == "shell"
    assert isinstance(emitted[2], ToolResultReceived)
    assert emitted[2].result == "stdout:\nhi"
    assert isinstance(emitted[3], TurnCompleted)
    assert emitted[3].final_text == "final"


def test_run_turn_keeps_error_tool_output_in_session(tmp_path: Path) -> None:
    session = Session()
    model_client = _FakeModelClient(
        turns=[
            [
                OutputItemDone(
                    item={
                        "type": "function_call",
                        "name": "shell",
                        "arguments": '{"command":"false"}',
                    }
                ),
                Completed(response_id="resp_tools"),
            ],
            [OutputTextDelta(delta="handled"), Completed(response_id="resp_final")],
        ]
    )
    router = _FakeToolRouter(
        specs=[{"type": "function", "function": {"name": "shell"}}],
        results=["[ERROR] Command failed"],
    )

    result = asyncio.run(
        run_turn(
            session=session,
            model_client=model_client,
            tool_router=router,
            cwd=tmp_path,
            user_input="run failing shell",
        )
    )

    assert result == "handled"
    assert session.to_prompt() == [
        {"role": "user", "content": "run failing shell"},
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "shell",
            "arguments": '{"command":"false"}',
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "[ERROR] Command failed"},
    ]
    assert model_client.calls[1]["messages"][1] == {
        "type": "function_call",
        "call_id": "call_1",
        "name": "shell",
        "arguments": '{"command":"false"}',
    }
    assert model_client.calls[1]["messages"][2] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "[ERROR] Command failed",
    }


def test_run_turn_aborts_immediately_when_tool_aborted(tmp_path: Path) -> None:
    session = Session()
    model_client = _FakeModelClient(
        turns=[
            [
                OutputItemDone(
                    item={
                        "type": "function_call",
                        "name": "write_file",
                        "arguments": '{"file_path":"x.txt","content":"hi"}',
                        "call_id": "call_abort",
                    }
                ),
                Completed(response_id="resp_tools"),
            ]
        ]
    )
    router = _AbortingToolRouter(
        specs=[{"type": "function", "function": {"name": "write_file"}}]
    )
    emitted: list[AgentEvent] = []

    async def on_event(event: AgentEvent) -> None:
        emitted.append(event)

    result = asyncio.run(
        run_turn(
            session=session,
            model_client=model_client,
            tool_router=router,
            cwd=tmp_path,
            user_input="write file",
            on_event=on_event,
        )
    )

    assert result == "Aborted by user."
    assert [event.type for event in emitted] == [
        "turn_started",
        "tool_call_dispatched",
        "turn_completed",
    ]
    assert isinstance(emitted[2], TurnCompleted)
    assert emitted[2].final_text == "Aborted by user."
    assert len(model_client.calls) == 1
    assert session.to_prompt() == [
        {"role": "user", "content": "write file"},
        {
            "type": "function_call",
            "call_id": "call_abort",
            "name": "write_file",
            "arguments": '{"file_path":"x.txt","content":"hi"}',
        },
    ]


def test_run_turn_uses_done_item_text_when_no_text_deltas(tmp_path: Path) -> None:
    session = Session()
    model_client = _FakeModelClient(
        turns=[
            [
                OutputItemDone(
                    item={
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "fallback text"}],
                    }
                ),
                Completed(response_id="resp_final"),
            ]
        ]
    )
    router = _FakeToolRouter(specs=[], results=[])

    result = asyncio.run(
        run_turn(
            session=session,
            model_client=model_client,
            tool_router=router,
            cwd=tmp_path,
            user_input="answer directly",
        )
    )

    assert result == "fallback text"


def test_run_turn_preserves_text_before_tool_calls_in_same_pass(tmp_path: Path) -> None:
    session = Session()
    model_client = _FakeModelClient(
        turns=[
            [
                OutputTextDelta(delta="checking "),
                OutputTextDelta(delta="now"),
                OutputItemDone(
                    item={
                        "type": "function_call",
                        "name": "read_file",
                        "arguments": '{"file_path":"README.md"}',
                        "call_id": "call_5",
                    }
                ),
                Completed(response_id="resp_tools"),
            ],
            [OutputTextDelta(delta="all set"), Completed(response_id="resp_final")],
        ]
    )
    router = _FakeToolRouter(
        specs=[{"type": "function", "function": {"name": "read_file"}}],
        results=["L1: # pycodex"],
    )

    result = asyncio.run(
        run_turn(
            session=session,
            model_client=model_client,
            tool_router=router,
            cwd=tmp_path,
            user_input="inspect readme",
        )
    )

    assert result == "all set"
    assert session.to_prompt() == [
        {"role": "user", "content": "inspect readme"},
        {"role": "assistant", "content": "checking now"},
        {
            "type": "function_call",
            "call_id": "call_5",
            "name": "read_file",
            "arguments": '{"file_path":"README.md"}',
        },
        {"role": "tool", "tool_call_id": "call_5", "content": "L1: # pycodex"},
    ]
    assert model_client.calls[1]["messages"] == session.to_prompt()
