from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from pycodex.approval.policy import ApprovalPolicy, ApprovalStore, ReviewDecision
from pycodex.core.agent import AgentEvent, ToolResultReceived, TurnCompleted, run_turn
from pycodex.core.config import Config
from pycodex.core.model_client import Completed, OutputItemDone, OutputTextDelta, ResponseEvent
from pycodex.core.session import Session
from pycodex.tools.base import ToolRegistry, ToolRouter
from pycodex.tools.orchestrator import OrchestratorConfig
from pycodex.tools.write_file import WriteFileTool

pytestmark = pytest.mark.agent_harness

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "approval_policy_scenarios.json"
_SCENARIOS = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


class _ScenarioModelClient:
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
            raise AssertionError("No scenario turn configured")
        for event in self._turns.pop(0):
            yield event


def _build_tool_router(ask_user_fn: Any) -> ToolRouter:
    registry = ToolRegistry(
        orchestrator=OrchestratorConfig(
            policy=ApprovalPolicy.ON_REQUEST,
            store=ApprovalStore(),
            ask_user_fn=ask_user_fn,
        )
    )
    registry.register(WriteFileTool())
    return ToolRouter(registry)


def _tool_payloads(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for item in messages:
        if item.get("role") != "tool":
            continue
        content = item.get("content")
        assert isinstance(content, str)
        payload = json.loads(content)
        assert isinstance(payload, dict)
        payloads.append(payload)
    return payloads


def test_harness_denied_produces_denied_tool_result_and_continues(tmp_path: Path) -> None:
    scenario = _SCENARIOS["denied"]
    events: list[AgentEvent] = []
    ask_count = 0

    async def ask_user_fn(_tool: Any, _args: dict[str, Any]) -> ReviewDecision:
        nonlocal ask_count
        ask_count += 1
        return ReviewDecision.DENIED

    model_client = _ScenarioModelClient(
        turns=[
            [OutputItemDone(item=scenario["call"]), Completed(response_id="resp_tool")],
            [
                OutputTextDelta(delta=scenario["assistant_after_tool"]),
                Completed(response_id="resp_done"),
            ],
        ]
    )

    result = asyncio.run(
        run_turn(
            session=Session(config=Config(model="test-model", api_key="test-key", cwd=tmp_path)),
            model_client=model_client,
            tool_router=_build_tool_router(ask_user_fn),
            cwd=tmp_path,
            user_input=scenario["user_input"],
            on_event=events.append,
        )
    )

    assert result == scenario["assistant_after_tool"]
    assert ask_count == 1
    assert not (tmp_path / "denied.txt").exists()
    assert len(model_client.calls) == 2
    payloads = _tool_payloads(model_client.calls[1]["messages"])
    assert len(payloads) == 1
    assert payloads[0]["success"] is False
    assert payloads[0]["error"]["code"] == "denied"
    assert isinstance(events[-1], TurnCompleted)
    assert events[-1].final_text == scenario["assistant_after_tool"]
    assert any(isinstance(event, ToolResultReceived) for event in events)


def test_harness_abort_stops_turn_immediately(tmp_path: Path) -> None:
    scenario = _SCENARIOS["abort"]
    events: list[AgentEvent] = []
    ask_count = 0

    async def ask_user_fn(_tool: Any, _args: dict[str, Any]) -> ReviewDecision:
        nonlocal ask_count
        ask_count += 1
        return ReviewDecision.ABORT

    model_client = _ScenarioModelClient(
        turns=[[OutputItemDone(item=scenario["call"]), Completed(response_id="resp_tool")]]
    )

    result = asyncio.run(
        run_turn(
            session=Session(config=Config(model="test-model", api_key="test-key", cwd=tmp_path)),
            model_client=model_client,
            tool_router=_build_tool_router(ask_user_fn),
            cwd=tmp_path,
            user_input=scenario["user_input"],
            on_event=events.append,
        )
    )

    assert result == "Aborted by user."
    assert ask_count == 1
    assert len(model_client.calls) == 1
    assert not (tmp_path / "abort.txt").exists()
    assert [event.type for event in events] == [
        "turn_started",
        "tool_call_dispatched",
        "turn_completed",
    ]
    assert isinstance(events[-1], TurnCompleted)
    assert events[-1].final_text == "Aborted by user."


def test_harness_session_approval_cache_skips_second_prompt(tmp_path: Path) -> None:
    scenario = _SCENARIOS["session_cache"]
    ask_count = 0

    async def ask_user_fn(_tool: Any, _args: dict[str, Any]) -> ReviewDecision:
        nonlocal ask_count
        ask_count += 1
        return ReviewDecision.APPROVED_FOR_SESSION

    model_client = _ScenarioModelClient(
        turns=[
            [
                OutputItemDone(item=scenario["calls"][0]),
                OutputItemDone(item=scenario["calls"][1]),
                Completed(response_id="resp_tools"),
            ],
            [
                OutputTextDelta(delta=scenario["assistant_after_tool"]),
                Completed(response_id="resp_done"),
            ],
        ]
    )

    result = asyncio.run(
        run_turn(
            session=Session(config=Config(model="test-model", api_key="test-key", cwd=tmp_path)),
            model_client=model_client,
            tool_router=_build_tool_router(ask_user_fn),
            cwd=tmp_path,
            user_input=scenario["user_input"],
        )
    )

    assert result == scenario["assistant_after_tool"]
    assert ask_count == 1
    assert (tmp_path / "cache.txt").read_text(encoding="utf-8") == "second"
    assert len(model_client.calls) == 2
    payloads = _tool_payloads(model_client.calls[1]["messages"])
    assert len(payloads) == 2
    assert payloads[0]["success"] is True
    assert payloads[1]["success"] is True
