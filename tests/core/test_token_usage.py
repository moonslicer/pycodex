from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pycodex.core.agent import AgentEvent, TurnCompleted, run_turn
from pycodex.core.model_client import Completed, OutputTextDelta, ResponseEvent
from pycodex.core.session import Session


class _FakeModelClient:
    def __init__(self, turns: list[list[ResponseEvent]]) -> None:
        self._turns = turns

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        instructions: str = "",
    ):
        _ = messages, tools, instructions
        if not self._turns:
            raise AssertionError("No configured turn events left")
        for event in self._turns.pop(0):
            yield event


class _NoopToolRouter:
    def tool_specs(self) -> list[dict[str, Any]]:
        return []

    async def dispatch(self, *, name: str, arguments: str | dict[str, Any], cwd: Path) -> str:
        _ = name, arguments, cwd
        raise AssertionError("dispatch should not be called")


def test_session_record_turn_usage_updates_cumulative_totals() -> None:
    session = Session()

    first = session.record_turn_usage({"input_tokens": 3, "output_tokens": 1})
    second = session.record_turn_usage({"input_tokens": 4, "output_tokens": 2})

    assert first == {
        "turn": {"input_tokens": 3, "output_tokens": 1},
        "cumulative": {"input_tokens": 3, "output_tokens": 1},
    }
    assert second == {
        "turn": {"input_tokens": 4, "output_tokens": 2},
        "cumulative": {"input_tokens": 7, "output_tokens": 3},
    }
    assert session.cumulative_usage() == {"input_tokens": 7, "output_tokens": 3}


def test_session_record_turn_usage_rejects_invalid_payload() -> None:
    session = Session()
    session.record_turn_usage({"input_tokens": 1, "output_tokens": 2})

    assert session.record_turn_usage({"input_tokens": -1, "output_tokens": 2}) is None
    assert session.record_turn_usage({"input_tokens": 1, "output_tokens": True}) is None
    assert session.record_turn_usage(None) is None
    assert session.cumulative_usage() == {"input_tokens": 1, "output_tokens": 2}


def test_run_turn_emits_monotonic_cumulative_usage(tmp_path: Path) -> None:
    session = Session()
    model_client = _FakeModelClient(
        turns=[
            [
                OutputTextDelta(delta="first"),
                Completed(usage={"input_tokens": 3, "output_tokens": 1}),
            ],
            [
                OutputTextDelta(delta="second"),
                Completed(usage={"input_tokens": 4, "output_tokens": 2}),
            ],
        ]
    )
    router = _NoopToolRouter()
    emitted: list[AgentEvent] = []

    async def on_event(event: AgentEvent) -> None:
        emitted.append(event)

    asyncio.run(
        run_turn(
            session=session,
            model_client=model_client,
            tool_router=router,
            cwd=tmp_path,
            user_input="turn one",
            on_event=on_event,
        )
    )
    asyncio.run(
        run_turn(
            session=session,
            model_client=model_client,
            tool_router=router,
            cwd=tmp_path,
            user_input="turn two",
            on_event=on_event,
        )
    )

    completed_events = [event for event in emitted if isinstance(event, TurnCompleted)]
    assert len(completed_events) == 2
    assert completed_events[0].usage == {
        "turn": {"input_tokens": 3, "output_tokens": 1},
        "cumulative": {"input_tokens": 3, "output_tokens": 1},
    }
    assert completed_events[1].usage == {
        "turn": {"input_tokens": 4, "output_tokens": 2},
        "cumulative": {"input_tokens": 7, "output_tokens": 3},
    }
