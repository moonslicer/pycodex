from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pycodex.core.tui_bridge as tui_bridge_module
import pytest
from pycodex.approval.policy import ReviewDecision
from pycodex.core.agent import TurnCompleted, TurnStarted
from pycodex.core.config import Config
from pycodex.core.session import Session
from pycodex.core.tui_bridge import TuiBridge


class _FakeModelClient:
    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ):
        _ = messages, tools
        if False:  # pragma: no cover
            yield None


class _FakeToolRouter:
    def tool_specs(self) -> list[dict[str, Any]]:
        return []

    async def dispatch(self, *, name: str, arguments: str | dict[str, Any], cwd: Path) -> str:
        _ = name, arguments, cwd
        return "ok"


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


def _session(tmp_path: Path) -> Session:
    return Session(config=Config(model="test-model", api_key="test-key", cwd=tmp_path))


class _LineReader:
    def __init__(self, lines: list[str]) -> None:
        self._lines = [f"{line}\n".encode() for line in lines]

    async def readline(self) -> bytes:
        await asyncio.sleep(0)
        if not self._lines:
            return b""
        return self._lines.pop(0)


def _reader_with_lines(lines: list[str]) -> _LineReader:
    return _LineReader(lines)


def test_thread_started_emitted_on_init(tmp_path: Path) -> None:
    events: list[Any] = []

    _ = TuiBridge(
        session=_session(tmp_path),
        model_client=_FakeModelClient(),
        tool_router=_FakeToolRouter(),
        cwd=tmp_path,
        emit_event=events.append,
    )

    assert len(events) == 1
    assert events[0].type == "thread.started"


def test_user_input_command_starts_turn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen_inputs: list[str] = []
    events: list[Any] = []

    async def fake_run_turn(
        *,
        session: Session,
        model_client: Any,
        tool_router: Any,
        cwd: Path,
        user_input: str,
        on_event: Any = None,
    ) -> str:
        _ = session, model_client, tool_router, cwd
        seen_inputs.append(user_input)
        assert on_event is not None
        on_event(TurnStarted(user_input=user_input))
        on_event(TurnCompleted(final_text="done"))
        return "done"

    monkeypatch.setattr(tui_bridge_module, "run_turn", fake_run_turn)

    bridge = TuiBridge(
        session=_session(tmp_path),
        model_client=_FakeModelClient(),
        tool_router=_FakeToolRouter(),
        cwd=tmp_path,
        emit_event=events.append,
    )

    reader = _reader_with_lines(
        [
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "user.input",
                    "params": {"text": "hello from tui"},
                }
            )
        ]
    )

    asyncio.run(bridge.run(reader=reader))

    assert seen_inputs == ["hello from tui"]
    assert [event.type for event in events] == [
        "thread.started",
        "turn.started",
        "turn.completed",
    ]


def test_interrupt_cancels_active_turn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[Any] = []
    started = asyncio.Event()

    async def fake_run_turn(
        *,
        session: Session,
        model_client: Any,
        tool_router: Any,
        cwd: Path,
        user_input: str,
        on_event: Any = None,
    ) -> str:
        _ = session, model_client, tool_router, cwd, user_input
        assert on_event is not None
        on_event(TurnStarted(user_input="in-flight"))
        started.set()
        await asyncio.Event().wait()
        return "unreachable"

    async def scenario() -> None:
        monkeypatch.setattr(tui_bridge_module, "run_turn", fake_run_turn)
        bridge = TuiBridge(
            session=_session(tmp_path),
            model_client=_FakeModelClient(),
            tool_router=_FakeToolRouter(),
            cwd=tmp_path,
            emit_event=events.append,
        )
        await bridge._handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "user.input",
                    "params": {"text": "hello"},
                }
            )
        )
        await started.wait()
        await bridge._handle_line(
            json.dumps({"jsonrpc": "2.0", "method": "interrupt", "params": {}})
        )
        if bridge._active_turn is not None:
            await bridge._active_turn

    asyncio.run(scenario())

    assert [event.type for event in events] == [
        "thread.started",
        "turn.started",
        "turn.failed",
    ]
    assert events[-1].error == "interrupted"


def test_unknown_commands_are_ignored_safely(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    events: list[Any] = []

    async def fake_run_turn(
        *,
        session: Session,
        model_client: Any,
        tool_router: Any,
        cwd: Path,
        user_input: str,
        on_event: Any = None,
    ) -> str:
        _ = session, model_client, tool_router, cwd, on_event
        calls.append(user_input)
        return "done"

    monkeypatch.setattr(tui_bridge_module, "run_turn", fake_run_turn)
    bridge = TuiBridge(
        session=_session(tmp_path),
        model_client=_FakeModelClient(),
        tool_router=_FakeToolRouter(),
        cwd=tmp_path,
        emit_event=events.append,
    )

    reader = _reader_with_lines(
        [
            "{not-json}",
            json.dumps({"jsonrpc": "2.0", "method": "unknown.method", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "method": 123, "params": {}}),
            json.dumps({"jsonrpc": "2.0", "method": "user.input", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "method": "user.input", "params": {"text": 123}}),
            json.dumps({"jsonrpc": "2.0", "method": "approval.response", "params": {}}),
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "approval.response",
                    "params": {"request_id": "req_1", "decision": "nope"},
                }
            ),
            json.dumps(["not", "an", "object"]),
        ]
    )

    asyncio.run(bridge.run(reader=reader))

    assert calls == []
    assert [event.type for event in events] == ["thread.started"]


def test_eof_cancels_active_turn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[Any] = []
    started = asyncio.Event()

    async def fake_run_turn(
        *,
        session: Session,
        model_client: Any,
        tool_router: Any,
        cwd: Path,
        user_input: str,
        on_event: Any = None,
    ) -> str:
        _ = session, model_client, tool_router, cwd, user_input
        assert on_event is not None
        on_event(TurnStarted(user_input="in-flight"))
        started.set()
        await asyncio.Event().wait()
        return "unreachable"

    class _EofAfterStartReader:
        def __init__(self) -> None:
            self._sent = False

        async def readline(self) -> bytes:
            await asyncio.sleep(0)
            if not self._sent:
                self._sent = True
                return (
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "method": "user.input",
                            "params": {"text": "hello"},
                        }
                    ).encode()
                    + b"\n"
                )
            await started.wait()
            return b""

    async def scenario() -> None:
        monkeypatch.setattr(tui_bridge_module, "run_turn", fake_run_turn)
        bridge = TuiBridge(
            session=_session(tmp_path),
            model_client=_FakeModelClient(),
            tool_router=_FakeToolRouter(),
            cwd=tmp_path,
            emit_event=events.append,
        )
        await bridge.run(reader=_EofAfterStartReader())

    asyncio.run(scenario())

    assert [event.type for event in events] == [
        "thread.started",
        "turn.started",
        "turn.failed",
    ]
    assert events[-1].error == "interrupted"


def test_approval_request_emitted_and_unblocks_on_matching_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[Any] = []

    async def scenario() -> None:
        bridge: TuiBridge | None = None

        async def fake_run_turn(
            *,
            session: Session,
            model_client: Any,
            tool_router: Any,
            cwd: Path,
            user_input: str,
            on_event: Any = None,
        ) -> str:
            _ = session, model_client, tool_router, cwd, user_input
            assert bridge is not None
            assert on_event is not None
            on_event(TurnStarted(user_input="needs approval"))
            decision_task = asyncio.create_task(
                bridge.request_approval(
                    _FakeTool("write_file"),
                    {"file_path": "notes.txt"},
                )
            )
            await asyncio.sleep(0)
            approval_event = events[-1]
            assert approval_event.type == "approval.request"
            assert approval_event.turn_id == "turn_1"
            assert approval_event.preview == '{"arg_count": 1, "arg_keys": ["file_path"]}'
            assert "notes.txt" not in approval_event.preview
            await bridge._handle_line(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "approval.response",
                        "params": {
                            "request_id": approval_event.request_id,
                            "decision": "approved_for_session",
                        },
                    }
                )
            )
            assert await decision_task == ReviewDecision.APPROVED_FOR_SESSION
            on_event(TurnCompleted(final_text="done"))
            return "done"

        monkeypatch.setattr(tui_bridge_module, "run_turn", fake_run_turn)
        bridge = TuiBridge(
            session=_session(tmp_path),
            model_client=_FakeModelClient(),
            tool_router=_FakeToolRouter(),
            cwd=tmp_path,
            emit_event=events.append,
        )
        await bridge._handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "user.input",
                    "params": {"text": "hello"},
                }
            )
        )
        if bridge._active_turn is not None:
            await bridge._active_turn

    asyncio.run(scenario())

    assert [event.type for event in events] == [
        "thread.started",
        "turn.started",
        "approval.request",
        "turn.completed",
    ]


def test_approval_response_ignores_unknown_request_id_and_invalid_decision(tmp_path: Path) -> None:
    events: list[Any] = []

    async def scenario() -> None:
        bridge = TuiBridge(
            session=_session(tmp_path),
            model_client=_FakeModelClient(),
            tool_router=_FakeToolRouter(),
            cwd=tmp_path,
            emit_event=events.append,
        )
        bridge._active_turn_id = "turn_1"
        decision_task = asyncio.create_task(
            bridge.request_approval(_FakeTool("shell"), {"command": "pwd"})
        )
        await asyncio.sleep(0)
        approval_event = events[-1]
        assert approval_event.type == "approval.request"

        await bridge._handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "approval.response",
                    "params": {
                        "request_id": "unknown",
                        "decision": "approved",
                    },
                }
            )
        )
        await asyncio.sleep(0)
        assert not decision_task.done()

        await bridge._handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "approval.response",
                    "params": {
                        "request_id": approval_event.request_id,
                        "decision": "maybe",
                    },
                }
            )
        )
        await asyncio.sleep(0)
        assert not decision_task.done()

        await bridge._handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "approval.response",
                    "params": {
                        "request_id": approval_event.request_id,
                        "decision": "abort",
                    },
                }
            )
        )
        assert await decision_task == ReviewDecision.ABORT

    asyncio.run(scenario())


def test_approval_response_logs_unknown_request_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bridge = TuiBridge(
        session=_session(tmp_path),
        model_client=_FakeModelClient(),
        tool_router=_FakeToolRouter(),
        cwd=tmp_path,
        emit_event=lambda _: None,
    )

    bridge._handle_approval_response({"request_id": "unknown", "decision": "approved"})

    captured = capsys.readouterr()
    assert "unknown request_id 'unknown'" in captured.err


def test_request_approval_denies_when_pending_queue_full(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bridge = TuiBridge(
        session=_session(tmp_path),
        model_client=_FakeModelClient(),
        tool_router=_FakeToolRouter(),
        cwd=tmp_path,
        emit_event=lambda _: None,
    )
    bridge._active_turn_id = "turn_1"
    monkeypatch.setattr(tui_bridge_module, "_MAX_PENDING_APPROVALS", 0)

    async def scenario() -> None:
        decision = await bridge.request_approval(_FakeTool("shell"), {"command": "pwd"})
        assert decision == ReviewDecision.DENIED
        assert bridge._pending_approvals == {}

    asyncio.run(scenario())

    captured = capsys.readouterr()
    assert "approval queue full" in captured.err


def test_approval_request_requires_active_turn(tmp_path: Path) -> None:
    bridge = TuiBridge(
        session=_session(tmp_path),
        model_client=_FakeModelClient(),
        tool_router=_FakeToolRouter(),
        cwd=tmp_path,
        emit_event=lambda _: None,
    )

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="outside active turn"):
            await bridge.request_approval(_FakeTool("shell"), {"command": "pwd"})

    asyncio.run(scenario())


def test_request_approval_cleans_pending_on_emit_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bridge = TuiBridge(
        session=_session(tmp_path),
        model_client=_FakeModelClient(),
        tool_router=_FakeToolRouter(),
        cwd=tmp_path,
        emit_event=lambda _: None,
    )
    bridge._active_turn_id = "turn_1"

    def fail_emit(self: TuiBridge, event: Any) -> None:
        _ = event
        raise RuntimeError("emit failed")

    monkeypatch.setattr(TuiBridge, "_emit_protocol_event", fail_emit)

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="emit failed"):
            await bridge.request_approval(_FakeTool("shell"), {"command": "pwd"})
        assert bridge._pending_approvals == {}

    asyncio.run(scenario())
