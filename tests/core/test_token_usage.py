from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pycodex.core.agent import AgentEvent, TurnCompleted, run_turn
from pycodex.core.compaction import (
    CompactionContext,
    CompactionOrchestrator,
    CompactionPlan,
    LocalSummaryV1Implementation,
    _estimate_prompt_tokens,
)
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


class _CaptureStrategy:
    def __init__(self) -> None:
        self.context: CompactionContext | None = None
        self.name = "capture"

    def plan(self, context: CompactionContext) -> CompactionPlan | None:
        self.context = context
        return None


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


def test_compaction_uses_api_input_tokens_as_primary_trigger_signal() -> None:
    session = Session()
    session.append_user_message("u1")
    session.append_assistant_message("a1")
    session.record_turn_usage({"input_tokens": 123, "output_tokens": 7})

    strategy = _CaptureStrategy()
    orchestrator = CompactionOrchestrator(
        strategy=strategy,
        implementation=LocalSummaryV1Implementation(),
        context_window_tokens=1000,
    )

    asyncio.run(orchestrator.compact(session))

    assert strategy.context is not None
    assert strategy.context.api_input_tokens == 123
    assert strategy.context.prompt_tokens_estimate == 123


def test_compaction_falls_back_to_character_estimate_without_api_usage() -> None:
    session = Session()
    session.append_user_message("u1")
    session.append_assistant_message("a1")

    strategy = _CaptureStrategy()
    orchestrator = CompactionOrchestrator(
        strategy=strategy,
        implementation=LocalSummaryV1Implementation(),
        context_window_tokens=1000,
    )

    asyncio.run(orchestrator.compact(session))

    assert strategy.context is not None
    assert strategy.context.api_input_tokens == 0
    assert strategy.context.prompt_tokens_estimate == _estimate_prompt_tokens(session.to_prompt())
