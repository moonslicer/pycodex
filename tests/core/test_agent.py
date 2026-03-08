from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
from pycodex.core.agent import (
    Agent,
    AgentEvent,
    ContextCompacted,
    ContextPressure,
    TextDeltaReceived,
    ToolCallDispatched,
    ToolResultReceived,
    TurnCompleted,
    TurnStarted,
    run_turn,
)
from pycodex.core.agent_profile import AgentProfile
from pycodex.core.compaction import CompactionApplied
from pycodex.core.config import Config
from pycodex.core.model_client import Completed, OutputItemDone, OutputTextDelta, ResponseEvent
from pycodex.core.rollout_recorder import RolloutRecorder
from pycodex.core.rollout_replay import replay_rollout
from pycodex.core.session import Session
from pycodex.core.skills.injector import build_skill_injection_plan
from pycodex.core.skills.manager import SkillRegistry
from pycodex.core.skills.models import SkillDependencies, SkillEnvVarDependency, SkillMetadata
from pycodex.tools.orchestrator import ToolAborted


class _FakeModelClient:
    def __init__(self, turns: list[list[ResponseEvent]]) -> None:
        self._turns = turns
        self.calls: list[dict[str, Any]] = []

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        instructions: str = "",
    ):
        self.calls.append(
            {
                "messages": [dict(message) for message in messages],
                "tools": [dict(spec) for spec in tools],
                "instructions": instructions,
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


@dataclass(slots=True)
class _BlockingToolRouter:
    specs: list[dict[str, Any]]
    dispatch_calls: list[dict[str, Any]] = field(default_factory=list, init=False)
    started: asyncio.Event = field(default_factory=asyncio.Event, init=False)

    def tool_specs(self) -> list[dict[str, Any]]:
        return [dict(spec) for spec in self.specs]

    async def dispatch(self, *, name: str, arguments: str | dict[str, Any], cwd: Path) -> str:
        self.dispatch_calls.append({"name": name, "arguments": arguments, "cwd": cwd})
        self.started.set()
        await asyncio.Event().wait()
        return "unreachable"


@dataclass(slots=True)
class _SkillsManagerStub:
    registry: SkillRegistry

    def get_registry(self, **_: object) -> SkillRegistry:
        return self.registry


def _skill_metadata(
    name: str,
    skill_path: Path,
    *,
    dependencies: SkillDependencies | None = None,
) -> SkillMetadata:
    resolved = skill_path.resolve()
    return SkillMetadata(
        name=name,
        description=f"{name} description",
        short_description=None,
        path_to_skill_md=resolved,
        skill_root=resolved.parent,
        scope="repo",
        dependencies=dependencies,
    )


def _registry_with_skills(skills: tuple[SkillMetadata, ...]) -> SkillRegistry:
    by_name = {skill.name: skill for skill in skills}
    by_path = {skill.path_to_skill_md: skill for skill in skills}
    return SkillRegistry(
        skills=skills,
        errors=(),
        ambiguous_names=frozenset(),
        by_name=MappingProxyType(by_name),
        by_path=MappingProxyType(by_path),
    )


@dataclass(slots=True)
class _RecordingCompactionOrchestrator:
    calls: int = 0

    async def compact(self, session: Session) -> CompactionApplied | None:
        _ = session
        self.calls += 1
        return None


@dataclass(slots=True)
class _ApplyingCompactionOrchestrator:
    calls: int = 0

    async def compact(self, session: Session) -> CompactionApplied | None:
        _ = session
        self.calls += 1
        if self.calls > 1:
            return None
        return CompactionApplied(
            strategy="threshold_v1",
            implementation="local_summary_v1",
            replace_start=0,
            replace_end=3,
            replaced_items=3,
            estimated_prompt_tokens=9100,
            context_window_tokens=10000,
            remaining_ratio=0.09,
            threshold_ratio=0.2,
            summary_text="[compaction.summary.v1]\nConversation summary:\n- user: old",
        )


@dataclass(slots=True, frozen=True)
class _ThresholdStrategy:
    threshold_ratio: float = 0.2


@dataclass(slots=True)
class _PressureOnlyCompactionOrchestrator:
    strategy: _ThresholdStrategy = field(default_factory=_ThresholdStrategy)
    context_window_tokens: int = 100
    calls: int = 0

    async def compact(self, session: Session) -> CompactionApplied | None:
        _ = session
        self.calls += 1
        return None


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
            "instructions": "",
        }
    ]
    assert session.to_prompt() == [
        {"role": "user", "content": "say hi"},
        {"role": "assistant", "content": "hello world"},
    ]


def test_run_turn_injects_skill_message_before_model_sampling(tmp_path: Path) -> None:
    session = Session(config=Config(cwd=tmp_path))
    model_client = _FakeModelClient(
        turns=[[OutputTextDelta(delta="done"), Completed(response_id="resp_1")]]
    )
    router = _FakeToolRouter(specs=[], results=[])

    skill_path = tmp_path / "alpha" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        "---\nname: alpha\ndescription: Alpha\n---\nUse alpha steps.\n",
        encoding="utf-8",
    )
    registry = _registry_with_skills((_skill_metadata("alpha", skill_path),))
    skills_manager = _SkillsManagerStub(registry=registry)

    result = asyncio.run(
        Agent(
            session=session,
            model_client=model_client,
            tool_router=router,
            cwd=tmp_path,
            skills_manager=skills_manager,
        ).run_turn("please run $alpha")
    )

    assert result == "done"
    messages = model_client.calls[0]["messages"]
    user_index = next(
        index
        for index, message in enumerate(messages)
        if message.get("role") == "user" and message.get("content") == "please run $alpha"
    )
    injected = messages[user_index + 1]
    assert injected["role"] == "user"
    assert injected["skill_injected"] is True
    assert injected["skill_name"] == "alpha"
    assert injected["skill_path"] == str(skill_path.resolve())
    assert "<skill>" in injected["content"]
    assert "<name>alpha</name>" in injected["content"]


def test_run_turn_injects_unavailable_before_skill_message(tmp_path: Path) -> None:
    session = Session(config=Config(cwd=tmp_path))
    model_client = _FakeModelClient(
        turns=[[OutputTextDelta(delta="done"), Completed(response_id="resp_1")]]
    )
    router = _FakeToolRouter(specs=[], results=[])

    skill_path = tmp_path / "alpha" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        "---\nname: alpha\ndescription: Alpha\n---\nUse alpha steps.\n",
        encoding="utf-8",
    )
    registry = _registry_with_skills((_skill_metadata("alpha", skill_path),))
    skills_manager = _SkillsManagerStub(registry=registry)

    user_input = "$missing and $alpha"
    asyncio.run(
        Agent(
            session=session,
            model_client=model_client,
            tool_router=router,
            cwd=tmp_path,
            skills_manager=skills_manager,
        ).run_turn(user_input)
    )

    messages = model_client.calls[0]["messages"]
    user_index = next(
        index
        for index, message in enumerate(messages)
        if message.get("role") == "user" and message.get("content") == user_input
    )
    unavailable = messages[user_index + 1]
    injected_skill = messages[user_index + 2]
    assert "<skill-unavailable>" in unavailable["content"]
    assert "<reason>skill not found</reason>" in unavailable["content"]
    assert unavailable["skill_reason"] == "skill not found"
    assert "<skill>" in injected_skill["content"]
    assert "<name>alpha</name>" in injected_skill["content"]


def test_run_turn_injects_env_var_unavailable_message_when_dependency_missing(
    tmp_path: Path,
) -> None:
    session = Session(config=Config(cwd=tmp_path))
    model_client = _FakeModelClient(
        turns=[[OutputTextDelta(delta="done"), Completed(response_id="resp_1")]]
    )
    router = _FakeToolRouter(specs=[], results=[])

    needs_path = tmp_path / "needs" / "SKILL.md"
    needs_path.parent.mkdir(parents=True)
    needs_path.write_text(
        "---\nname: needs\ndescription: Needs\n---\nUse needs steps.\n",
        encoding="utf-8",
    )
    needs = _skill_metadata(
        "needs",
        needs_path,
        dependencies=SkillDependencies(env_vars=(SkillEnvVarDependency(name="MISSING_ENV"),)),
    )
    registry = _registry_with_skills((needs,))
    skills_manager = _SkillsManagerStub(registry=registry)

    asyncio.run(
        Agent(
            session=session,
            model_client=model_client,
            tool_router=router,
            cwd=tmp_path,
            skills_manager=skills_manager,
        ).run_turn("please run $needs")
    )

    messages = model_client.calls[0]["messages"]
    user_index = next(
        index
        for index, message in enumerate(messages)
        if message.get("role") == "user" and message.get("content") == "please run $needs"
    )
    unavailable = messages[user_index + 1]
    assert "<skill-unavailable>" in unavailable["content"]
    assert "<reason>missing required env var: MISSING_ENV</reason>" in unavailable["content"]


def test_run_turn_does_not_reinject_existing_skill_message_on_resumed_session(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = Session(config=Config(cwd=tmp_path))
    model_client = _FakeModelClient(
        turns=[[OutputTextDelta(delta="done"), Completed(response_id="resp_1")]]
    )
    router = _FakeToolRouter(specs=[], results=[])

    skill_path = tmp_path / "alpha" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        "---\nname: alpha\ndescription: Alpha\n---\nUse alpha steps.\n",
        encoding="utf-8",
    )
    registry = _registry_with_skills((_skill_metadata("alpha", skill_path),))
    skills_manager = _SkillsManagerStub(registry=registry)
    user_input = "please run $alpha"

    prior_plan = build_skill_injection_plan(user_input=user_input, registry=registry)
    prior_history: list[dict[str, Any]] = [{"role": "user", "content": user_input}]
    for injected in prior_plan.messages:
        prior_history.append(
            {
                "role": "user",
                "content": injected.content,
                "skill_injected": True,
                "skill_name": injected.name,
                "skill_path": str(injected.path) if injected.path is not None else None,
                "skill_reason": injected.reason,
            }
        )
    session.restore_from_rollout(
        history=prior_history,
        cumulative_usage={"input_tokens": 0, "output_tokens": 0},
        turn_count=0,
    )

    caplog.set_level("DEBUG", logger="pycodex.core.agent")
    asyncio.run(
        Agent(
            session=session,
            model_client=model_client,
            tool_router=router,
            cwd=tmp_path,
            skills_manager=skills_manager,
        ).run_turn(user_input)
    )

    injected_messages = [
        message
        for message in model_client.calls[0]["messages"]
        if message.get("skill_injected") is True and message.get("skill_name") == "alpha"
    ]
    assert len(injected_messages) == 1
    assert any("skill.replay_skip" in record.getMessage() for record in caplog.records)


def test_run_turn_does_not_reemit_existing_unavailable_message_on_resumed_session(
    tmp_path: Path,
) -> None:
    session = Session(config=Config(cwd=tmp_path))
    model_client = _FakeModelClient(
        turns=[[OutputTextDelta(delta="done"), Completed(response_id="resp_1")]]
    )
    router = _FakeToolRouter(specs=[], results=[])
    registry = _registry_with_skills(())
    skills_manager = _SkillsManagerStub(registry=registry)
    missing_path = tmp_path / "missing" / "SKILL.md"
    user_input = f"[$ghost]({missing_path})"

    prior_plan = build_skill_injection_plan(user_input=user_input, registry=registry)
    prior_history: list[dict[str, Any]] = [{"role": "user", "content": user_input}]
    for injected in prior_plan.messages:
        prior_history.append(
            {
                "role": "user",
                "content": injected.content,
                "skill_injected": True,
                "skill_name": injected.name,
                "skill_path": str(injected.path) if injected.path is not None else None,
                "skill_reason": injected.reason,
            }
        )
    session.restore_from_rollout(
        history=prior_history,
        cumulative_usage={"input_tokens": 0, "output_tokens": 0},
        turn_count=0,
    )

    asyncio.run(
        Agent(
            session=session,
            model_client=model_client,
            tool_router=router,
            cwd=tmp_path,
            skills_manager=skills_manager,
        ).run_turn(user_input)
    )

    unavailable_messages = [
        message
        for message in model_client.calls[0]["messages"]
        if isinstance(message.get("content"), str) and "<skill-unavailable>" in message["content"]
    ]
    assert len(unavailable_messages) == 1


def test_run_turn_invokes_compaction_orchestrator_once_per_model_sample(tmp_path: Path) -> None:
    session = Session()
    model_client = _FakeModelClient(
        turns=[[OutputTextDelta(delta="hello"), Completed(response_id="resp_1")]]
    )
    router = _FakeToolRouter(specs=[], results=[])
    compaction = _RecordingCompactionOrchestrator()
    agent = Agent(
        session=session,
        model_client=model_client,
        tool_router=router,
        cwd=tmp_path,
        compaction_orchestrator=compaction,
    )

    result = asyncio.run(agent.run_turn("say hi"))

    assert result == "hello"
    assert compaction.calls == 1


def test_run_turn_emits_context_compacted_event(tmp_path: Path) -> None:
    session = Session()
    model_client = _FakeModelClient(
        turns=[[OutputTextDelta(delta="hello"), Completed(response_id="resp_1")]]
    )
    router = _FakeToolRouter(specs=[], results=[])
    compaction = _ApplyingCompactionOrchestrator()
    emitted: list[AgentEvent] = []

    async def on_event(event: AgentEvent) -> None:
        emitted.append(event)

    result = asyncio.run(
        Agent(
            session=session,
            model_client=model_client,
            tool_router=router,
            cwd=tmp_path,
            on_event=on_event,
            compaction_orchestrator=compaction,
        ).run_turn("say hi")
    )

    assert result == "hello"
    assert [event.type for event in emitted] == [
        "turn_started",
        "context_compacted",
        "text_delta_received",
        "turn_completed",
    ]
    assert isinstance(emitted[1], ContextCompacted)
    assert emitted[1].strategy == "threshold_v1"
    assert emitted[1].implementation == "local_summary_v1"
    assert emitted[1].replaced_items == 3


def test_run_turn_emits_context_pressure_warning_before_compaction(tmp_path: Path) -> None:
    session = Session()
    session.record_turn_usage({"input_tokens": 75, "output_tokens": 0})
    model_client = _FakeModelClient(
        turns=[[OutputTextDelta(delta="hello"), Completed(response_id="resp_1")]]
    )
    router = _FakeToolRouter(specs=[], results=[])
    compaction = _PressureOnlyCompactionOrchestrator()
    emitted: list[AgentEvent] = []

    async def on_event(event: AgentEvent) -> None:
        emitted.append(event)

    result = asyncio.run(
        Agent(
            session=session,
            model_client=model_client,
            tool_router=router,
            cwd=tmp_path,
            on_event=on_event,
            compaction_orchestrator=compaction,
        ).run_turn("say hi")
    )

    assert result == "hello"
    assert [event.type for event in emitted] == [
        "turn_started",
        "context_pressure",
        "text_delta_received",
        "turn_completed",
    ]
    assert isinstance(emitted[1], ContextPressure)
    assert emitted[1].context_window_tokens == 100
    assert emitted[1].estimated_prompt_tokens == 75
    assert emitted[1].remaining_ratio == pytest.approx(0.25)


def test_run_turn_builds_compaction_orchestrator_from_config(tmp_path: Path) -> None:
    config = Config(
        model="test-model",
        api_key="test-key",
        cwd=tmp_path,
        compaction_threshold_ratio=0.15,
        compaction_context_window_tokens=321,
        compaction_strategy="threshold_v1",
        compaction_implementation="local_summary_v1",
        compaction_options={
            "strategy": {"keep_recent_items": 3},
            "implementation": {"max_lines": 2},
        },
    )
    session = Session(config=config)
    model_client = _FakeModelClient(
        turns=[[OutputTextDelta(delta="hello"), Completed(response_id="resp_1")]]
    )
    router = _FakeToolRouter(specs=[], results=[])
    agent = Agent(
        session=session,
        model_client=model_client,
        tool_router=router,
        cwd=tmp_path,
    )

    result = asyncio.run(agent.run_turn("say hi"))

    assert result == "hello"
    assert agent.compaction_orchestrator is not None
    strategy = agent.compaction_orchestrator.strategy
    implementation = agent.compaction_orchestrator.implementation
    assert strategy.name == "threshold_v1"
    assert strategy.threshold_ratio == 0.15
    assert strategy.keep_recent_items == 3
    assert implementation.name == "local_summary_v1"
    assert implementation.max_lines == 2
    assert agent.compaction_orchestrator.context_window_tokens == 321


def test_run_turn_compaction_summary_is_deterministic_from_config(tmp_path: Path) -> None:
    config = Config(
        model="test-model",
        api_key="test-key",
        cwd=tmp_path,
        compaction_threshold_ratio=0.2,
        compaction_context_window_tokens=20,
        compaction_strategy="threshold_v1",
        compaction_implementation="local_summary_v1",
        compaction_options={
            "strategy": {"keep_recent_items": 4, "min_replace_items": 2},
            "implementation": {"max_lines": 4, "max_line_chars": 80},
        },
    )

    def build_seeded_session() -> Session:
        seeded = Session(config=config)
        for index in range(6):
            seeded.append_user_message(f"user-{index}")
            seeded.append_assistant_message(f"assistant-{index}")
        return seeded

    model_turn = [[OutputTextDelta(delta="done"), Completed(response_id="resp_1")]]
    session_one = build_seeded_session()
    session_two = build_seeded_session()

    result_one = asyncio.run(
        Agent(
            session=session_one,
            model_client=_FakeModelClient(turns=[list(model_turn[0])]),
            tool_router=_FakeToolRouter(specs=[], results=[]),
            cwd=tmp_path,
        ).run_turn("continue")
    )
    result_two = asyncio.run(
        Agent(
            session=session_two,
            model_client=_FakeModelClient(turns=[list(model_turn[0])]),
            tool_router=_FakeToolRouter(specs=[], results=[]),
            cwd=tmp_path,
        ).run_turn("continue")
    )

    assert result_one == "done"
    assert result_two == "done"

    def extract_summary_text(prompt: list[dict[str, Any]]) -> str:
        for item in prompt:
            if item.get("role") != "system":
                continue
            content = item.get("content", "")
            if "[compaction.summary.v1]" in str(content):
                return str(content)
        raise AssertionError("expected compaction summary block in session history")

    summary_one = extract_summary_text(session_one.to_prompt())
    summary_two = extract_summary_text(session_two.to_prompt())
    assert summary_one == summary_two
    assert summary_one.startswith("[compaction.summary.v1]\nConversation summary:")
    assert "strategy=" not in summary_one


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
        {"role": "assistant", "content": "done"},
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
        "text_delta_received",
        "turn_completed",
    ]
    assert isinstance(emitted[0], TurnStarted)
    assert emitted[0].user_input == "run shell"
    assert isinstance(emitted[1], ToolCallDispatched)
    assert emitted[1].call_id == "call_99"
    assert emitted[1].name == "shell"
    assert isinstance(emitted[2], ToolResultReceived)
    assert emitted[2].result == "stdout:\nhi"
    assert isinstance(emitted[3], TextDeltaReceived)
    assert emitted[3].delta == "final"
    assert isinstance(emitted[4], TurnCompleted)
    assert emitted[4].final_text == "final"


def test_run_turn_threads_usage_to_turn_completed_event(tmp_path: Path) -> None:
    session = Session()
    model_client = _FakeModelClient(
        turns=[
            [
                OutputTextDelta(delta="final"),
                Completed(
                    response_id="resp_usage",
                    usage={"input_tokens": 10, "output_tokens": 5},
                ),
            ]
        ]
    )
    router = _FakeToolRouter(specs=[], results=[])
    emitted: list[AgentEvent] = []

    async def on_event(event: AgentEvent) -> None:
        emitted.append(event)

    result = asyncio.run(
        run_turn(
            session=session,
            model_client=model_client,
            tool_router=router,
            cwd=tmp_path,
            user_input="say hi",
            on_event=on_event,
        )
    )

    assert result == "final"
    assert [event.type for event in emitted] == [
        "turn_started",
        "text_delta_received",
        "turn_completed",
    ]
    assert isinstance(emitted[1], TextDeltaReceived)
    assert emitted[1].delta == "final"
    assert isinstance(emitted[2], TurnCompleted)
    assert emitted[2].usage == {
        "turn": {"input_tokens": 10, "output_tokens": 5},
        "cumulative": {"input_tokens": 10, "output_tokens": 5},
    }


def test_run_turn_emits_text_delta_metadata_from_model_stream(tmp_path: Path) -> None:
    session = Session()
    model_client = _FakeModelClient(
        turns=[
            [
                OutputTextDelta(delta="hi", item_id="msg_1", output_index=2),
                Completed(response_id="resp_usage"),
            ]
        ]
    )
    router = _FakeToolRouter(specs=[], results=[])
    emitted: list[AgentEvent] = []

    async def on_event(event: AgentEvent) -> None:
        emitted.append(event)

    result = asyncio.run(
        run_turn(
            session=session,
            model_client=model_client,
            tool_router=router,
            cwd=tmp_path,
            user_input="say hi",
            on_event=on_event,
        )
    )

    assert result == "hi"
    assert [event.type for event in emitted] == [
        "turn_started",
        "text_delta_received",
        "turn_completed",
    ]
    assert isinstance(emitted[1], TextDeltaReceived)
    assert emitted[1].delta == "hi"
    assert emitted[1].item_id == "msg_1"
    assert emitted[1].output_index == 2


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
        {"role": "assistant", "content": "handled"},
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
    router = _AbortingToolRouter(specs=[{"type": "function", "function": {"name": "write_file"}}])
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
        {"role": "tool", "tool_call_id": "call_abort", "content": "aborted by user"},
    ]


def test_run_turn_abort_stops_remaining_tool_calls_in_same_turn(tmp_path: Path) -> None:
    session = Session()
    model_client = _FakeModelClient(
        turns=[
            [
                OutputItemDone(
                    item={
                        "type": "function_call",
                        "name": "write_file",
                        "arguments": '{"file_path":"x.txt","content":"hi"}',
                        "call_id": "call_abort_first",
                    }
                ),
                OutputItemDone(
                    item={
                        "type": "function_call",
                        "name": "shell",
                        "arguments": '{"command":"echo should-not-run"}',
                        "call_id": "call_after_abort",
                    }
                ),
                Completed(response_id="resp_tools"),
            ]
        ]
    )
    router = _AbortingToolRouter(
        specs=[
            {"type": "function", "function": {"name": "write_file"}},
            {"type": "function", "function": {"name": "shell"}},
        ]
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
            user_input="write then shell",
            on_event=on_event,
        )
    )

    assert result == "Aborted by user."
    assert len(router.dispatch_calls) == 1
    assert router.dispatch_calls[0]["name"] == "write_file"
    assert [event.type for event in emitted] == [
        "turn_started",
        "tool_call_dispatched",
        "turn_completed",
    ]
    assert len(model_client.calls) == 1
    assert session.to_prompt() == [
        {"role": "user", "content": "write then shell"},
        {
            "type": "function_call",
            "call_id": "call_abort_first",
            "name": "write_file",
            "arguments": '{"file_path":"x.txt","content":"hi"}',
        },
        {"role": "tool", "tool_call_id": "call_abort_first", "content": "aborted by user"},
    ]


def test_run_turn_cancellation_appends_interrupted_tool_output(tmp_path: Path) -> None:
    session = Session()
    model_client = _FakeModelClient(
        turns=[
            [
                OutputItemDone(
                    item={
                        "type": "function_call",
                        "name": "shell",
                        "arguments": '{"command":"sleep 30"}',
                        "call_id": "call_interrupt",
                    }
                ),
                Completed(response_id="resp_tools"),
            ]
        ]
    )
    router = _BlockingToolRouter(specs=[{"type": "function", "function": {"name": "shell"}}])

    async def scenario() -> None:
        task = asyncio.create_task(
            run_turn(
                session=session,
                model_client=model_client,
                tool_router=router,
                cwd=tmp_path,
                user_input="run long command",
            )
        )
        await router.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert session.to_prompt() == [
        {"role": "user", "content": "run long command"},
        {
            "type": "function_call",
            "call_id": "call_interrupt",
            "name": "shell",
            "arguments": '{"command":"sleep 30"}',
        },
        {"role": "tool", "tool_call_id": "call_interrupt", "content": "interrupted"},
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
    assert session.to_prompt() == [
        {"role": "user", "content": "answer directly"},
        {"role": "assistant", "content": "fallback text"},
    ]


def test_run_turn_concatenates_multiple_done_item_texts_without_deltas(tmp_path: Path) -> None:
    session = Session()
    model_client = _FakeModelClient(
        turns=[
            [
                OutputItemDone(
                    item={
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "first "}],
                    }
                ),
                OutputItemDone(
                    item={
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "second"}],
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

    assert result == "first second"
    assert session.to_prompt() == [
        {"role": "user", "content": "answer directly"},
        {"role": "assistant", "content": "first second"},
    ]


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
        {"role": "assistant", "content": "all set"},
    ]
    assert model_client.calls[1]["messages"] == [
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


def test_agent_prepends_initial_context_once_across_turns(tmp_path: Path) -> None:
    config = Config(cwd=tmp_path)
    session = Session(config=config)
    model_client = _FakeModelClient(
        turns=[
            [OutputTextDelta(delta="first"), Completed(response_id="resp_1")],
            [OutputTextDelta(delta="second"), Completed(response_id="resp_2")],
        ]
    )
    router = _FakeToolRouter(specs=[], results=[])
    agent = Agent(
        session=session,
        model_client=model_client,
        tool_router=router,
        cwd=tmp_path,
    )

    result_1 = asyncio.run(agent.run_turn("turn one"))
    result_2 = asyncio.run(agent.run_turn("turn two"))

    assert result_1 == "first"
    assert result_2 == "second"
    assert {"role": "assistant", "content": "first"} in model_client.calls[1]["messages"]
    prompt = session.to_prompt()
    assert sum(1 for item in prompt if item.get("role") == "system") == 1
    assert prompt[0]["role"] == "system"


def test_agent_persists_initial_context_items_to_rollout(tmp_path: Path) -> None:
    rollout_path = tmp_path / "rollout.jsonl"
    config = Config(cwd=tmp_path)
    session = Session(config=config)
    session.configure_rollout_recorder(
        recorder=RolloutRecorder(path=rollout_path),
        path=rollout_path,
    )
    model_client = _FakeModelClient(
        turns=[[OutputTextDelta(delta="hi"), Completed(response_id="resp_1")]]
    )
    router = _FakeToolRouter(specs=[], results=[])
    agent = Agent(session=session, model_client=model_client, tool_router=router, cwd=tmp_path)

    asyncio.run(agent.run_turn("hello"))

    state = replay_rollout(rollout_path)
    sys_items = [item for item in state.history if item.get("role") == "system"]
    assert len(sys_items) >= 1


def test_agent_does_not_repersist_initial_context_on_resumed_session(tmp_path: Path) -> None:
    """Resumed sessions with initial_context_injected=True must not re-write initial context."""
    rollout_path = tmp_path / "rollout.jsonl"
    config = Config(cwd=tmp_path)

    # First session: write initial context + one turn
    session1 = Session(config=config)
    session1.configure_rollout_recorder(
        recorder=RolloutRecorder(path=rollout_path),
        path=rollout_path,
    )
    model_client1 = _FakeModelClient(
        turns=[[OutputTextDelta(delta="hello"), Completed(response_id="resp_1")]]
    )
    asyncio.run(
        Agent(
            session=session1,
            model_client=model_client1,
            tool_router=_FakeToolRouter(specs=[], results=[]),
            cwd=tmp_path,
        ).run_turn("first")
    )

    state_after_first = replay_rollout(rollout_path)
    sys_count_after_first = sum(
        1 for item in state_after_first.history if item.get("role") == "system"
    )

    # Second session: resume with initial_context_injected=True — should NOT re-write
    session2 = Session(config=config, thread_id=state_after_first.thread_id)
    session2.restore_from_rollout(
        history=state_after_first.history,
        cumulative_usage=state_after_first.cumulative_usage,
        turn_count=state_after_first.turn_count,
    )
    session2.configure_rollout_recorder(
        recorder=RolloutRecorder(path=rollout_path),
        path=rollout_path,
    )
    model_client2 = _FakeModelClient(
        turns=[[OutputTextDelta(delta="world"), Completed(response_id="resp_2")]]
    )
    asyncio.run(
        Agent(
            session=session2,
            model_client=model_client2,
            tool_router=_FakeToolRouter(specs=[], results=[]),
            cwd=tmp_path,
        ).run_turn("second")
    )

    state_after_second = replay_rollout(rollout_path)
    sys_count_after_second = sum(
        1 for item in state_after_second.history if item.get("role") == "system"
    )
    # System count unchanged: no extra system messages injected on resume
    assert sys_count_after_second == sys_count_after_first


@pytest.mark.asyncio
async def test_multi_compaction_multi_resume_history_and_llm_prompt_are_correct(
    tmp_path: Path,
) -> None:
    """
    Verifies that across multiple compactions and multiple resumes:
    1. The JSONL replay produces the correct in-memory history.
    2. The LLM prompt sent each turn is consistent with that history.
    3. Initial context items are never duplicated.
    4. Compaction indices remain correct after every resume.
    """
    # context_window_tokens=20 ensures the char-based estimate fires compaction after turn 2:
    # the env-context sys msg alone is ~25 tokens > 70% threshold of 20 tokens.
    # keep_recent_items=2 means only 2 messages are kept individually after each compaction.
    rollout_path = tmp_path / "rollout.jsonl"
    config = Config(
        cwd=tmp_path,
        compaction_context_window_tokens=20,
        compaction_options={
            "strategy": {"keep_recent_items": 2, "min_replace_items": 2, "threshold_ratio": 0.3}
        },
    )

    def _make_agent(session: Session, responses: list[str]) -> tuple[Agent, _FakeModelClient]:
        mc = _FakeModelClient(
            turns=[
                [OutputTextDelta(delta=r), Completed(response_id=f"resp_{i}")]
                for i, r in enumerate(responses)
            ]
        )
        return Agent(
            session=session,
            model_client=mc,
            tool_router=_FakeToolRouter(specs=[], results=[]),
            cwd=tmp_path,
        ), mc

    def _resume_session() -> Session:
        state = replay_rollout(rollout_path)
        s = Session(config=config, thread_id=state.thread_id)
        s.restore_from_rollout(
            history=state.history,
            cumulative_usage=state.cumulative_usage,
            turn_count=state.turn_count,
        )
        s.configure_rollout_recorder(recorder=RolloutRecorder(path=rollout_path), path=rollout_path)
        return s

    def _summary_blocks(prompt: list[dict]) -> list[dict]:
        return [m for m in prompt if "[compaction.summary.v1]" in str(m.get("content", ""))]

    def _plain_sys(prompt: list[dict]) -> list[dict]:
        return [
            m
            for m in prompt
            if m.get("role") == "system"
            and "[compaction.summary.v1]" not in str(m.get("content", ""))
        ]

    # --- Session 1: 2 turns — compaction fires on turn 2 ---
    s1 = Session(config=config)
    s1.configure_rollout_recorder(recorder=RolloutRecorder(path=rollout_path), path=rollout_path)
    agent1, mc1 = _make_agent(s1, ["reply-1", "reply-2"])
    await agent1.run_turn("msg-1")
    await agent1.run_turn("msg-2")

    # Turn 2 prompt: compaction fired before sampling.
    # Compaction replaced [sys, msg-1] (indices 0-1), keeping [reply-1, msg-2] as recent.
    # So reply-1 IS individually visible in the turn-2 prompt; msg-1 is inside the summary.
    turn2_prompt = mc1.calls[1]["messages"]
    assert len(_summary_blocks(turn2_prompt)) >= 1, "compaction must fire before turn 2"
    individual_msgs_t2 = [m for m in turn2_prompt if m.get("role") in ("user", "assistant")]
    assert len(individual_msgs_t2) <= 2
    individual_contents_t2 = {str(m.get("content", "")) for m in individual_msgs_t2}
    assert "msg-1" not in individual_contents_t2  # compacted into summary
    assert "reply-1" in individual_contents_t2  # kept as recent item
    assert "msg-2" in individual_contents_t2  # current user message

    state1 = replay_rollout(rollout_path)
    assert len(_plain_sys(state1.history)) <= 1  # env-context not duplicated

    # --- Session 2: resume with initial_context_injected=True.
    # The env-context sys was compacted into summary1 — it is NOT re-injected as a standalone
    # message; it lives inside the summary block. ---
    s2 = _resume_session()
    agent2, mc2 = _make_agent(s2, ["reply-3", "reply-4"])
    await agent2.run_turn("msg-3")
    await agent2.run_turn("msg-4")

    # Both session-2 prompts must have summary blocks
    for call_idx, call in enumerate(mc2.calls):
        assert len(_summary_blocks(call["messages"])) >= 1, (
            f"session 2 turn {call_idx + 1} prompt is missing summary block"
        )
    # msg-1 must never appear individually in any session-2 call
    for call in mc2.calls:
        indiv = {
            str(m.get("content", ""))
            for m in call["messages"]
            if m.get("role") in ("user", "assistant")
        }
        assert "msg-1" not in indiv, "msg-1 leaked individually in session 2"

    state2 = replay_rollout(rollout_path)
    assert len(_plain_sys(state2.history)) <= 1

    # --- Session 3: resume again, verify full prompt shape ---
    s3 = _resume_session()
    agent3, mc3 = _make_agent(s3, ["reply-5"])
    await agent3.run_turn("msg-5")

    prompt = mc3.calls[0]["messages"]

    # Prompt must start with a system message (first summary block)
    assert prompt[0]["role"] == "system"

    # Multiple compaction summary blocks must be present by now
    assert len(_summary_blocks(prompt)) >= 1, "session 3 prompt must contain compaction summaries"

    # No duplicate system messages
    for i in range(len(prompt) - 1):
        assert not (
            prompt[i]["role"] == "system"
            and prompt[i + 1]["role"] == "system"
            and prompt[i]["content"] == prompt[i + 1]["content"]
        ), f"duplicate system message at index {i}"

    # At most keep_recent_items=2 individual user/assistant messages remain
    individual_msgs = [m for m in prompt if m.get("role") in ("user", "assistant")]
    assert len(individual_msgs) <= 2

    # msg-5 is the last user message
    user_msgs = [m["content"] for m in prompt if m.get("role") == "user"]
    assert user_msgs[-1] == "msg-5"

    # Messages from earlier rounds that were compacted must NOT appear individually.
    # (reply-4 may still be a recent item depending on compaction boundary)
    individual_contents = {str(m.get("content", "")) for m in individual_msgs}
    deeply_compacted = {"msg-1", "reply-1", "msg-2", "reply-2", "msg-3"}
    leaked = deeply_compacted & individual_contents
    assert not leaked, f"deeply compacted messages appeared individually: {leaked}"

    # --- Final replay: no plain sys duplication ---
    state_final = replay_rollout(rollout_path)
    assert len(_plain_sys(state_final.history)) <= 1


def test_run_turn_threads_profile_instructions_to_model_client(tmp_path: Path) -> None:
    profile = AgentProfile(
        name="support",
        instructions="You are a support specialist.",
        instruction_filenames=("AGENTS.md",),
        enabled_tools=None,
    )
    session = Session(config=Config(cwd=tmp_path, profile=profile))
    model_client = _FakeModelClient(
        turns=[[OutputTextDelta(delta="ok"), Completed(response_id="resp_1")]]
    )
    router = _FakeToolRouter(specs=[], results=[])

    result = asyncio.run(
        run_turn(
            session=session,
            model_client=model_client,
            tool_router=router,
            cwd=tmp_path,
            user_input="hello",
        )
    )

    assert result == "ok"
    assert model_client.calls[0]["instructions"] == "You are a support specialist."
