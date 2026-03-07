from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import pycodex.core.tui_bridge as tui_bridge_module
import pytest
from pycodex.approval.policy import ReviewDecision
from pycodex.core.agent import TurnCompleted, TurnStarted
from pycodex.core.config import Config
from pycodex.core.rollout_replay import ReplayState
from pycodex.core.session import Session
from pycodex.core.session_store import SessionSummaryRecord
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

    bridge = _new_bridge(tmp_path, events)

    assert len(events) == 1
    assert events[0].type == "thread.started"
    assert events[0].thread_id == bridge.session.thread_id


def test_thread_started_uses_resumed_session_thread_id(tmp_path: Path) -> None:
    events: list[Any] = []
    resumed_thread_id = "replayed-thread-id"
    resumed_session = Session(
        config=Config(model="test-model", api_key="test-key", cwd=tmp_path),
        thread_id=resumed_thread_id,
    )

    _ = TuiBridge(
        session=resumed_session,
        model_client=_FakeModelClient(),
        tool_router=_FakeToolRouter(),
        cwd=tmp_path,
        emit_event=events.append,
    )

    assert len(events) == 1
    assert events[0].type == "thread.started"
    assert events[0].thread_id == resumed_thread_id


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


def test_slash_status_emits_session_status(tmp_path: Path) -> None:
    events: list[Any] = []
    bridge = _new_bridge(tmp_path, events)
    bridge.session.append_user_message("old")
    bridge.session.append_assistant_message("reply")
    assert bridge.session.replace_range_with_system_summary(
        replace_start=0,
        replace_end=2,
        summary_text="[compaction.summary.v1]\nConversation summary:\n- old",
    )
    bridge.session.mark_turn_completed()
    bridge.session.record_turn_usage({"input_tokens": 12, "output_tokens": 7})

    asyncio.run(bridge._handle_line(_user_input_line("/status")))

    assert _event_types(events) == ["thread.started", "session.status"]
    status_event = events[-1]
    assert status_event.thread_id == bridge.session.thread_id
    assert status_event.turn_count == 1
    assert status_event.input_tokens == 12
    assert status_event.output_tokens == 7
    assert status_event.context_window_tokens == 128_000
    assert status_event.compaction_count == 1


def test_slash_status_allowed_during_active_turn(tmp_path: Path) -> None:
    events: list[Any] = []

    async def scenario() -> None:
        bridge = _new_bridge(tmp_path, events)
        blocker = asyncio.Event()
        bridge._active_turn = asyncio.create_task(blocker.wait())
        await bridge._handle_line(_user_input_line("/status"))
        bridge._active_turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await bridge._active_turn

    asyncio.run(scenario())

    assert _event_types(events) == ["thread.started", "session.status"]
    status_event = events[-1]
    assert status_event.context_window_tokens == 128_000
    assert status_event.compaction_count == 0


def test_slash_resume_emits_filtered_session_list(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[Any] = []
    bridge = _new_bridge(tmp_path, events)
    current_thread_id = bridge.session.thread_id
    monkeypatch.setattr(
        tui_bridge_module,
        "list_sessions",
        lambda *, config, limit: [
            SessionSummaryRecord(
                thread_id=current_thread_id,
                status="closed",
                turn_count=1,
                token_total=2,
                last_user_message="current",
                date="20260101",
                updated_at="2026-01-01T00:00:00Z",
                size_bytes=1024,
            ),
            SessionSummaryRecord(
                thread_id="other-thread",
                status="incomplete",
                turn_count=3,
                token_total=9,
                last_user_message="other",
                date="20260102",
                updated_at="2026-01-02T00:00:00Z",
                size_bytes=2048,
            ),
        ],
    )

    asyncio.run(bridge._handle_line(_user_input_line("/resume")))

    assert _event_types(events) == ["thread.started", "session.listed"]
    listed_event = events[-1]
    assert len(listed_event.sessions) == 1
    assert listed_event.sessions[0].thread_id == "other-thread"
    assert listed_event.sessions[0].status == "incomplete"
    assert listed_event.sessions[0].updated_at == "2026-01-02T00:00:00Z"
    assert listed_event.sessions[0].size_bytes == 2048


def test_slash_resume_with_no_sessions_emits_empty_list(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[Any] = []
    bridge = _new_bridge(tmp_path, events)
    monkeypatch.setattr(tui_bridge_module, "list_sessions", lambda *, config, limit: [])

    asyncio.run(bridge._handle_line(_user_input_line("/resume")))

    assert _event_types(events) == ["thread.started", "session.listed"]
    assert events[-1].sessions == []


def test_slash_resume_blocked_when_turn_is_active(tmp_path: Path) -> None:
    events: list[Any] = []

    async def scenario() -> None:
        bridge = _new_bridge(tmp_path, events)
        blocker = asyncio.Event()
        bridge._active_turn = asyncio.create_task(blocker.wait())
        await bridge._handle_line(_user_input_line("/resume"))
        bridge._active_turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await bridge._active_turn

    asyncio.run(scenario())

    assert _event_types(events) == ["thread.started", "slash.blocked"]
    blocked_event = events[-1]
    assert blocked_event.command == "resume"
    assert blocked_event.reason == "active_turn"


def test_slash_resume_list_error_emits_session_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[Any] = []
    bridge = _new_bridge(tmp_path, events)

    def fail_list_sessions(*, config: Config, limit: int) -> list[SessionSummaryRecord]:
        _ = config, limit
        raise RuntimeError("list failed")

    monkeypatch.setattr(tui_bridge_module, "list_sessions", fail_list_sessions)

    asyncio.run(bridge._handle_line(_user_input_line("/resume")))

    assert _event_types(events) == ["thread.started", "session.error"]
    assert events[-1].operation == "list"


def test_slash_new_emits_new_thread_started(tmp_path: Path) -> None:
    events: list[Any] = []
    bridge = _new_bridge(tmp_path, events)
    old_thread_id = bridge.session.thread_id

    asyncio.run(bridge._handle_line(_user_input_line("/new")))

    assert _event_types(events) == ["thread.started", "thread.started"]
    new_thread_event = events[-1]
    assert new_thread_event.thread_id != old_thread_id
    assert bridge.session.thread_id == new_thread_event.thread_id


def test_slash_new_blocked_when_turn_is_active(tmp_path: Path) -> None:
    events: list[Any] = []

    async def scenario() -> None:
        bridge = _new_bridge(tmp_path, events)
        blocker = asyncio.Event()
        bridge._active_turn = asyncio.create_task(blocker.wait())
        await bridge._handle_line(_user_input_line("/new"))
        bridge._active_turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await bridge._active_turn

    asyncio.run(scenario())

    assert _event_types(events) == ["thread.started", "slash.blocked"]
    blocked_event = events[-1]
    assert blocked_event.command == "new"
    assert blocked_event.reason == "active_turn"


def test_unknown_slash_command_emits_slash_unknown(tmp_path: Path) -> None:
    events: list[Any] = []
    bridge = _new_bridge(tmp_path, events)

    asyncio.run(bridge._handle_line(_user_input_line("/nope")))

    assert _event_types(events) == ["thread.started", "slash.unknown"]
    assert events[-1].command == "nope"


def test_bare_slash_command_emits_slash_unknown_without_crash(tmp_path: Path) -> None:
    events: list[Any] = []
    bridge = _new_bridge(tmp_path, events)

    asyncio.run(bridge._handle_line(_user_input_line("/")))

    assert _event_types(events) == ["thread.started", "slash.unknown"]
    assert events[-1].command == ""


def test_activate_session_replaces_bridge_session_and_clears_pending_approvals(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[Any] = []
    bridge = _new_bridge(tmp_path, events)
    bridge.session.append_user_message("hello")
    close_calls = 0

    async def fake_close_rollout(_self: Session) -> None:
        nonlocal close_calls
        close_calls += 1

    monkeypatch.setattr(Session, "close_rollout", fake_close_rollout)
    bridge._pending_approvals["req_1"] = tui_bridge_module._PendingApproval()
    new_session = Session(
        config=Config(model="test-model", api_key="test-key", cwd=tmp_path),
        thread_id="new-thread-id",
    )

    asyncio.run(bridge._activate_session(new_session))

    assert close_calls == 1
    assert bridge.session.thread_id == "new-thread-id"
    assert bridge._pending_approvals == {}
    assert _event_types(events) == ["thread.started", "thread.started"]
    assert events[-1].thread_id == "new-thread-id"


def test_activate_session_skips_close_for_pristine_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[Any] = []
    bridge = _new_bridge(tmp_path, events)
    close_calls = 0

    async def fake_close_rollout(_self: Session) -> None:
        nonlocal close_calls
        close_calls += 1

    monkeypatch.setattr(Session, "close_rollout", fake_close_rollout)
    new_session = Session(
        config=Config(model="test-model", api_key="test-key", cwd=tmp_path),
        thread_id="new-thread-id",
    )

    asyncio.run(bridge._activate_session(new_session))

    assert close_calls == 0
    assert bridge.session.thread_id == "new-thread-id"
    assert _event_types(events) == ["thread.started", "thread.started"]
    assert events[-1].thread_id == "new-thread-id"


def test_session_new_method_emits_thread_started(tmp_path: Path) -> None:
    events: list[Any] = []
    bridge = _new_bridge(tmp_path, events)
    old_thread_id = bridge.session.thread_id

    asyncio.run(
        bridge._handle_line(json.dumps({"jsonrpc": "2.0", "method": "session.new", "params": {}}))
    )

    assert _event_types(events) == ["thread.started", "thread.started"]
    assert events[-1].thread_id != old_thread_id
    assert bridge.session.thread_id == events[-1].thread_id


def test_session_new_method_active_turn_emits_session_error(tmp_path: Path) -> None:
    events: list[Any] = []

    async def scenario() -> None:
        bridge = _new_bridge(tmp_path, events)
        blocker = asyncio.Event()
        bridge._active_turn = asyncio.create_task(blocker.wait())
        await bridge._handle_line(
            json.dumps({"jsonrpc": "2.0", "method": "session.new", "params": {}})
        )
        bridge._active_turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await bridge._active_turn

    asyncio.run(scenario())

    assert _event_types(events) == ["thread.started", "session.error"]
    assert events[-1].operation == "new"


def test_session_resume_method_missing_thread_id_emits_session_error(tmp_path: Path) -> None:
    events: list[Any] = []
    bridge = _new_bridge(tmp_path, events)

    asyncio.run(
        bridge._handle_line(
            json.dumps({"jsonrpc": "2.0", "method": "session.resume", "params": {}})
        )
    )

    assert _event_types(events) == ["thread.started", "session.error"]
    assert events[-1].operation == "resume"


def test_session_resume_method_same_thread_emits_session_error(tmp_path: Path) -> None:
    events: list[Any] = []
    bridge = _new_bridge(tmp_path, events)

    asyncio.run(
        bridge._handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "session.resume",
                    "params": {"thread_id": bridge.session.thread_id},
                }
            )
        )
    )

    assert _event_types(events) == ["thread.started", "session.error"]
    assert events[-1].operation == "resume"


def test_session_resume_method_active_turn_emits_session_error(tmp_path: Path) -> None:
    events: list[Any] = []

    async def scenario() -> None:
        bridge = _new_bridge(tmp_path, events)
        blocker = asyncio.Event()
        bridge._active_turn = asyncio.create_task(blocker.wait())
        await bridge._handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "session.resume",
                    "params": {"thread_id": "other-thread"},
                }
            )
        )
        bridge._active_turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await bridge._active_turn

    asyncio.run(scenario())

    assert _event_types(events) == ["thread.started", "session.error"]
    assert events[-1].operation == "resume"


def test_session_resume_method_unknown_thread_id_emits_session_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[Any] = []
    bridge = _new_bridge(tmp_path, events)

    async def fail_resolve_resume_rollout_path(
        *,
        config: Config,
        resume: str,
        sessions_root: Path | None = None,
    ) -> Path:
        _ = config, resume, sessions_root
        raise FileNotFoundError("unknown session")

    monkeypatch.setattr(
        tui_bridge_module,
        "resolve_resume_rollout_path",
        fail_resolve_resume_rollout_path,
    )

    asyncio.run(
        bridge._handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "session.resume",
                    "params": {"thread_id": "missing-thread"},
                }
            )
        )
    )

    assert _event_types(events) == ["thread.started", "session.error"]
    assert events[-1].operation == "resume"


def test_session_resume_method_replays_and_emits_hydrated_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[Any] = []
    bridge = _new_bridge(tmp_path, events)
    replay_path = tmp_path / "rollout-20260101-000000000000-replayed-thread.jsonl"
    replay_state = ReplayState(
        thread_id="replayed-thread",
        history=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ],
        cumulative_usage={"input_tokens": 5, "output_tokens": 8},
        turn_count=3,
        status="closed",
        warnings=[],
        session_meta=None,
        session_closed=None,
    )

    async def fake_resolve_resume_rollout_path(
        *,
        config: Config,
        resume: str,
        sessions_root: Path | None = None,
    ) -> Path:
        _ = config, resume, sessions_root
        return replay_path

    monkeypatch.setattr(
        tui_bridge_module,
        "resolve_resume_rollout_path",
        fake_resolve_resume_rollout_path,
    )
    monkeypatch.setattr(tui_bridge_module, "replay_rollout", lambda path: replay_state)

    asyncio.run(
        bridge._handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "session.resume",
                    "params": {"thread_id": "replayed-thread"},
                }
            )
        )
    )

    assert _event_types(events) == ["thread.started", "thread.started", "session.hydrated"]
    assert events[-2].thread_id == "replayed-thread"
    assert events[-1].thread_id == "replayed-thread"
    assert len(events[-1].turns) == 1
    assert events[-1].turns[0].user_text == "hello"
    assert events[-1].turns[0].assistant_text == "hi there"
    assert events[-1].turns[0].compaction_summary is None
    assert bridge.session.thread_id == "replayed-thread"
    assert bridge.session.completed_turn_count() == 3


def test_session_resume_method_hydrates_compaction_summary_on_next_turn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[Any] = []
    bridge = _new_bridge(tmp_path, events)
    replay_path = tmp_path / "rollout-20260101-000000000000-replayed-thread.jsonl"
    replay_state = ReplayState(
        thread_id="replayed-thread",
        history=[
            {
                "role": "system",
                "content": "[compaction.summary.v1]\nConversation summary:\n- earlier",
            },
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ],
        cumulative_usage={"input_tokens": 5, "output_tokens": 8},
        turn_count=3,
        status="closed",
        warnings=[],
        session_meta=None,
        session_closed=None,
    )

    async def fake_resolve_resume_rollout_path(
        *,
        config: Config,
        resume: str,
        sessions_root: Path | None = None,
    ) -> Path:
        _ = config, resume, sessions_root
        return replay_path

    monkeypatch.setattr(
        tui_bridge_module,
        "resolve_resume_rollout_path",
        fake_resolve_resume_rollout_path,
    )
    monkeypatch.setattr(tui_bridge_module, "replay_rollout", lambda path: replay_state)

    asyncio.run(
        bridge._handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "session.resume",
                    "params": {"thread_id": "replayed-thread"},
                }
            )
        )
    )

    hydrated_event = events[-1]
    assert hydrated_event.type == "session.hydrated"
    assert len(hydrated_event.turns) == 1
    assert hydrated_event.turns[0].compaction_summary is not None
    assert "[compaction.summary.v1]" in hydrated_event.turns[0].compaction_summary


def test_session_resume_method_activate_session_error_emits_session_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[Any] = []
    bridge = _new_bridge(tmp_path, events)
    replay_path = tmp_path / "rollout-20260101-000000000000-replayed-thread.jsonl"
    replay_state = ReplayState(
        thread_id="replayed-thread",
        history=[{"role": "user", "content": "hello"}],
        cumulative_usage={"input_tokens": 5, "output_tokens": 8},
        turn_count=3,
        status="closed",
        warnings=[],
        session_meta=None,
        session_closed=None,
    )

    async def fake_resolve_resume_rollout_path(
        *,
        config: Config,
        resume: str,
        sessions_root: Path | None = None,
    ) -> Path:
        _ = config, resume, sessions_root
        return replay_path

    async def fail_activate_session(self: TuiBridge, new_session: Session) -> None:
        _ = self, new_session
        raise RuntimeError("activate failed")

    monkeypatch.setattr(
        tui_bridge_module,
        "resolve_resume_rollout_path",
        fake_resolve_resume_rollout_path,
    )
    monkeypatch.setattr(tui_bridge_module, "replay_rollout", lambda path: replay_state)
    monkeypatch.setattr(TuiBridge, "_activate_session", fail_activate_session)

    asyncio.run(
        bridge._handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "session.resume",
                    "params": {"thread_id": "replayed-thread"},
                }
            )
        )
    )

    assert _event_types(events) == ["thread.started", "session.error"]
    assert events[-1].operation == "resume"


def test_session_new_method_activate_session_error_emits_session_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[Any] = []
    bridge = _new_bridge(tmp_path, events)

    async def fail_activate_session(self: TuiBridge, new_session: Session) -> None:
        _ = self, new_session
        raise RuntimeError("activate failed")

    monkeypatch.setattr(TuiBridge, "_activate_session", fail_activate_session)

    asyncio.run(
        bridge._handle_line(json.dumps({"jsonrpc": "2.0", "method": "session.new", "params": {}}))
    )

    assert _event_types(events) == ["thread.started", "session.error"]
    assert events[-1].operation == "new"


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
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    bridge = TuiBridge(
        session=_session(tmp_path),
        model_client=_FakeModelClient(),
        tool_router=_FakeToolRouter(),
        cwd=tmp_path,
        emit_event=lambda _: None,
    )

    with caplog.at_level(logging.WARNING, logger="pycodex.core.tui_bridge"):
        bridge._handle_approval_response({"request_id": "unknown", "decision": "approved"})

    assert "unknown request_id 'unknown'" in caplog.text


def test_request_approval_denies_when_pending_queue_full(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
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

    with caplog.at_level(logging.WARNING, logger="pycodex.core.tui_bridge"):
        asyncio.run(scenario())

    assert "approval queue full" in caplog.text


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
