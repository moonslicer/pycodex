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

ABORT_TEXT = "Aborted by user."
INTERRUPTED_ERROR = "interrupted"


class _FakeModelClient:
    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        instructions: str = "",
    ):
        _ = messages, tools, instructions
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


def _make_approval_response_line(request_id: str, decision: str) -> str:
    """Build a JSON-RPC approval.response line for use in tests."""
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "approval.response",
            "params": {"request_id": request_id, "decision": decision},
        }
    )


def _event_types(events: list[Any]) -> list[str]:
    """Extract event type strings for compact assertions."""
    return [e.type for e in events]


def _new_bridge(tmp_path: Path, events: list[Any]) -> TuiBridge:
    return TuiBridge(
        session=_session(tmp_path),
        model_client=_FakeModelClient(),
        tool_router=_FakeToolRouter(),
        cwd=tmp_path,
        emit_event=events.append,
    )


def _user_input_line(text: str) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "user.input",
            "params": {"text": text},
        }
    )


def test_thread_started_emitted_on_init(tmp_path: Path) -> None:
    events: list[Any] = []

    _ = _new_bridge(tmp_path, events)

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

    bridge = _new_bridge(tmp_path, events)

    reader = _reader_with_lines([_user_input_line("hello from tui")])

    asyncio.run(bridge.run(reader=reader))

    assert seen_inputs == ["hello from tui"]
    assert _event_types(events) == [
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
        bridge = _new_bridge(tmp_path, events)
        await bridge._handle_line(_user_input_line("hello"))
        await started.wait()
        await bridge._handle_line(
            json.dumps({"jsonrpc": "2.0", "method": "interrupt", "params": {}})
        )
        if bridge._active_turn is not None:
            await bridge._active_turn

    asyncio.run(scenario())

    assert _event_types(events) == [
        "thread.started",
        "turn.started",
        "turn.failed",
    ]
    assert events[-1].error == INTERRUPTED_ERROR


def test_abort_completion_emits_turn_completed_not_failed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
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
        _ = session, model_client, tool_router, cwd, user_input
        assert on_event is not None
        on_event(TurnStarted(user_input="in-flight"))
        on_event(TurnCompleted(final_text=ABORT_TEXT))
        return ABORT_TEXT

    async def scenario() -> None:
        monkeypatch.setattr(tui_bridge_module, "run_turn", fake_run_turn)
        bridge = _new_bridge(tmp_path, events)
        await bridge._handle_line(_user_input_line("hello"))
        if bridge._active_turn is not None:
            await bridge._active_turn

    asyncio.run(scenario())

    assert _event_types(events) == [
        "thread.started",
        "turn.started",
        "turn.completed",
    ]
    assert events[-1].final_text == ABORT_TEXT


def test_unknown_command_during_active_turn_is_noop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[Any] = []
    started = asyncio.Event()
    allow_complete = asyncio.Event()

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
        await allow_complete.wait()
        on_event(TurnCompleted(final_text="done"))
        return "done"

    async def scenario() -> None:
        monkeypatch.setattr(tui_bridge_module, "run_turn", fake_run_turn)
        bridge = _new_bridge(tmp_path, events)
        await bridge._handle_line(_user_input_line("hello"))
        await started.wait()
        await bridge._handle_line(
            json.dumps({"jsonrpc": "2.0", "method": "unknown.method", "params": {}})
        )
        assert bridge._active_turn is not None
        assert not bridge._active_turn.done()
        allow_complete.set()
        await bridge._active_turn

    asyncio.run(scenario())

    assert _event_types(events) == [
        "thread.started",
        "turn.started",
        "turn.completed",
    ]
    assert events[-1].final_text == "done"


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
    bridge = _new_bridge(tmp_path, events)

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
    assert _event_types(events) == ["thread.started"]


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
        bridge = _new_bridge(tmp_path, events)
        await bridge.run(reader=_EofAfterStartReader())

    asyncio.run(scenario())

    assert _event_types(events) == [
        "thread.started",
        "turn.started",
        "turn.failed",
    ]
    assert events[-1].error == INTERRUPTED_ERROR


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


def test_render_approval_preview_shell_includes_command_preview_and_timeout() -> None:
    preview_json = tui_bridge_module._render_approval_preview(
        tool_name="shell",
        args={"command": "ls   -lrt", "timeout_ms": 5000},
    )
    preview = json.loads(preview_json)

    assert preview["mode"] == "shell"
    assert preview["command_preview"] == "ls -lrt"
    assert preview["timeout_ms"] == 5000
    assert preview["arg_count"] == 2
    assert preview["arg_keys"] == ["command", "timeout_ms"]


def test_render_approval_preview_shell_redacts_sensitive_tokens() -> None:
    preview_json = tui_bridge_module._render_approval_preview(
        tool_name="shell",
        args={
            "command": (
                "API_KEY=abc123 curl -H Authorization:BearerToken --password hunter2 "
                "--token=xyz --cookie session=abcdef"
            )
        },
    )
    preview = json.loads(preview_json)
    command_preview = preview.get("command_preview")
    assert isinstance(command_preview, str)
    assert "abc123" not in command_preview
    assert "hunter2" not in command_preview
    assert "xyz" not in command_preview
    assert "abcdef" not in command_preview
    assert "***REDACTED***" in command_preview


def test_render_approval_preview_non_shell_remains_shape_only() -> None:
    preview_json = tui_bridge_module._render_approval_preview(
        tool_name="write_file",
        args={"file_path": "notes.txt", "content": "hello"},
    )
    preview = json.loads(preview_json)

    assert preview == {
        "arg_count": 2,
        "arg_keys": ["content", "file_path"],
    }


# ---------------------------------------------------------------------------
# _sanitize_shell_command_preview - truncation boundary
# ---------------------------------------------------------------------------


def test_sanitize_shell_command_preview_truncates_at_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tui_bridge_module, "_MAX_SHELL_COMMAND_PREVIEW_CHARS", 10)
    long_cmd = "echo " + "a" * 20
    result = tui_bridge_module._sanitize_shell_command_preview(long_cmd)
    assert len(result) == 13  # 10 chars + "..."
    assert result.endswith("...")


def test_sanitize_shell_command_preview_no_truncation_at_exact_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tui_bridge_module, "_MAX_SHELL_COMMAND_PREVIEW_CHARS", 10)
    cmd = "a" * 10
    result = tui_bridge_module._sanitize_shell_command_preview(cmd)
    assert result == cmd
    assert not result.endswith("...")


# ---------------------------------------------------------------------------
# Shell preview - empty / whitespace-only command omits command_preview
# ---------------------------------------------------------------------------


def test_render_approval_preview_shell_empty_command_omits_preview() -> None:
    preview = json.loads(
        tui_bridge_module._render_approval_preview(tool_name="shell", args={"command": ""})
    )
    assert "command_preview" not in preview


def test_render_approval_preview_shell_whitespace_command_omits_preview() -> None:
    preview = json.loads(
        tui_bridge_module._render_approval_preview(tool_name="shell", args={"command": "   "})
    )
    assert "command_preview" not in preview


def test_render_approval_preview_shell_missing_command_omits_preview() -> None:
    preview = json.loads(tui_bridge_module._render_approval_preview(tool_name="shell", args={}))
    assert "command_preview" not in preview


# ---------------------------------------------------------------------------
# Shell preview - timeout_ms edge cases
# ---------------------------------------------------------------------------


def test_render_approval_preview_shell_zero_timeout_omitted() -> None:
    preview = json.loads(
        tui_bridge_module._render_approval_preview(
            tool_name="shell", args={"command": "pwd", "timeout_ms": 0}
        )
    )
    assert "timeout_ms" not in preview


def test_render_approval_preview_shell_negative_timeout_omitted() -> None:
    preview = json.loads(
        tui_bridge_module._render_approval_preview(
            tool_name="shell", args={"command": "pwd", "timeout_ms": -1}
        )
    )
    assert "timeout_ms" not in preview


def test_render_approval_preview_shell_boolean_timeout_omitted() -> None:
    # bool is a subclass of int; True == 1 but must be excluded.
    preview = json.loads(
        tui_bridge_module._render_approval_preview(
            tool_name="shell", args={"command": "pwd", "timeout_ms": True}
        )
    )
    assert "timeout_ms" not in preview


# ---------------------------------------------------------------------------
# Approval response - duplicate response to same request_id is ignored
# ---------------------------------------------------------------------------


def test_approval_response_duplicate_is_ignored(tmp_path: Path) -> None:
    async def scenario() -> None:
        bridge = TuiBridge(
            session=_session(tmp_path),
            model_client=_FakeModelClient(),
            tool_router=_FakeToolRouter(),
            cwd=tmp_path,
            emit_event=lambda _: None,
        )
        bridge._active_turn_id = "turn_1"
        decision_task = asyncio.create_task(
            bridge.request_approval(_FakeTool("shell"), {"command": "pwd"})
        )
        await asyncio.sleep(0)
        pending = next(iter(bridge._pending_approvals.values()))

        # First response: approved
        await bridge._handle_line(
            _make_approval_response_line(next(iter(bridge._pending_approvals.keys())), "approved")
        )
        first_decision = pending.decision

        # Second response: denied - should be ignored
        await bridge._handle_line(
            _make_approval_response_line(next(iter(bridge._pending_approvals.keys())), "denied")
        )
        assert await decision_task == ReviewDecision.APPROVED
        assert first_decision == ReviewDecision.APPROVED

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# request_approval - tool name normalization
# ---------------------------------------------------------------------------


def test_request_approval_tool_without_name_attr_uses_unknown(tmp_path: Path) -> None:
    """An object with no 'name' attribute should normalize to 'unknown'."""

    class _NoNameTool:
        pass

    async def scenario() -> None:
        events: list[Any] = []
        bridge = TuiBridge(
            session=_session(tmp_path),
            model_client=_FakeModelClient(),
            tool_router=_FakeToolRouter(),
            cwd=tmp_path,
            emit_event=events.append,
        )
        bridge._active_turn_id = "turn_1"
        decision_task = asyncio.create_task(bridge.request_approval(_NoNameTool(), {"x": 1}))
        await asyncio.sleep(0)
        approval_event = events[-1]
        assert approval_event.tool == "unknown"

        await bridge._handle_line(_make_approval_response_line(approval_event.request_id, "denied"))
        assert await decision_task == ReviewDecision.DENIED

    asyncio.run(scenario())


def test_request_approval_non_string_name_attr_uses_unknown(tmp_path: Path) -> None:
    """A tool whose 'name' attribute is not a string should normalize to 'unknown'."""

    class _IntNameTool:
        name = 42

    async def scenario() -> None:
        events: list[Any] = []
        bridge = TuiBridge(
            session=_session(tmp_path),
            model_client=_FakeModelClient(),
            tool_router=_FakeToolRouter(),
            cwd=tmp_path,
            emit_event=events.append,
        )
        bridge._active_turn_id = "turn_1"
        decision_task = asyncio.create_task(bridge.request_approval(_IntNameTool(), {"x": 1}))
        await asyncio.sleep(0)
        approval_event = events[-1]
        assert approval_event.tool == "unknown"

        await bridge._handle_line(_make_approval_response_line(approval_event.request_id, "denied"))
        assert await decision_task == ReviewDecision.DENIED

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# _parse_approval_decision - direct unit tests for all branches
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("approved", ReviewDecision.APPROVED),
        ("denied", ReviewDecision.DENIED),
        ("approved_for_session", ReviewDecision.APPROVED_FOR_SESSION),
        ("abort", ReviewDecision.ABORT),
        ("maybe", None),
        ("", None),
        (None, None),
        (123, None),
        (True, None),
    ],
)
def test_parse_approval_decision(raw: Any, expected: ReviewDecision | None) -> None:
    assert tui_bridge_module._parse_approval_decision(raw) == expected
